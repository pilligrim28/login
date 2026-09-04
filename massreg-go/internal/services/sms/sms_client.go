package sms

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/massreg/massreg-go/internal/core/config"
	"github.com/massreg/massreg-go/internal/core/logger"
	"github.com/massreg/massreg-go/pkg/client"
)

// Service type constants
const (
	ServiceMicrosoft  = "Microsoft"
	ServiceGoogle     = "Google"
	ServiceApple      = "Apple"
	ServiceSnapchat   = "Snapchat"
	ServiceInstagram  = "Instagram"
	ServiceFacebook   = "Facebook"
	ServiceDiscord    = "Discord"
)

// SMSActivate service codes
var serviceCodes = map[string]string{
	ServiceMicrosoft:  "ot",
	ServiceGoogle:     "gm",
	ServiceApple:      "ap",
	ServiceSnapchat:   "sc",
	ServiceInstagram:  "ig",
	ServiceFacebook:   "fb",
	ServiceDiscord:    "dc",
}

// GetServiceCode returns the SMS-Activate service code for a given service
func GetServiceCode(service string) string {
	if code, ok := serviceCodes[service]; ok {
		return code
	}
	return "ot" // Default to "other"
}

// NumberStatus represents the status of a phone number
type NumberStatus int

const (
	NumberStatusPending NumberStatus = iota
	NumberStatusReady
	NumberStatusReceived
	NumberStatusCancelled
	NumberStatusTimeout
)

func (s NumberStatus) String() string {
	switch s {
	case NumberStatusPending:
		return "pending"
	case NumberStatusReady:
		return "ready"
	case NumberStatusReceived:
		return "received"
	case NumberStatusCancelled:
		return "cancelled"
	case NumberStatusTimeout:
		return "timeout"
	default:
		return "unknown"
	}
}

// PhoneNumber represents an activated phone number
type PhoneNumber struct {
	ID          string        `json:"id"`
	Number      string        `json:"number"`
	Country     string        `json:"country"`
	Service     string        `json:"service"`
	Status      NumberStatus  `json:"status"`
	SMSCode     string        `json:"sms_code,omitempty"`
	ActivatedAt time.Time     `json:"activated_at"`
	ExpiresAt   time.Time     `json:"expires_at"`
}

// SMSProvider represents an SMS provider with load balancing
type SMSProvider struct {
	Name          string
	APIKey        string
	APIURL        string
	Weight        int
	MaxConcurrent int
	currentLoad   int
	mu            sync.RWMutex
	httpClient    *client.HTTPClient
}

// SMSClient manages SMS activation across multiple providers
type SMSClient struct {
	config     config.SMSConfig
	providers  []*SMSProvider
	cache      sync.Map // Map[string]*PhoneNumber with TTL
	logger     *logger.Logger
	rateLimiter *RateLimiter
	currentIdx  int
	mu          sync.RWMutex
}

// RateLimiter implements token bucket rate limiting
type RateLimiter struct {
	tokens     int
	maxTokens  int
	refillRate time.Duration
	mu         sync.Mutex
	lastRefill time.Time
}

// NewRateLimiter creates a new rate limiter
func NewRateLimiter(maxTokens int, refillRate time.Duration) *RateLimiter {
	return &RateLimiter{
		tokens:     maxTokens,
		maxTokens:  maxTokens,
		refillRate: refillRate,
		lastRefill: time.Now(),
	}
}

// Wait waits until a token is available
func (rl *RateLimiter) Wait(ctx context.Context) error {
	for {
		if rl.tryAcquire() {
			return nil
		}

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
}

// tryAcquire tries to acquire a token
func (rl *RateLimiter) tryAcquire() bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	// Refill tokens based on elapsed time
	now := time.Now()
	elapsed := now.Sub(rl.lastRefill)
	tokensToAdd := int(elapsed / rl.refillRate)
	
	if tokensToAdd > 0 {
		rl.tokens = min(rl.maxTokens, rl.tokens+tokensToAdd)
		rl.lastRefill = now
	}

	if rl.tokens > 0 {
		rl.tokens--
		return true
	}

	return false
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// NewSMSClient creates a new SMS client
func NewSMSClient(cfg config.SMSConfig, log *logger.Logger) (*SMSClient, error) {
	providers := make([]*SMSProvider, 0, len(cfg.Providers))

	for _, p := range cfg.Providers {
		httpClient, err := client.NewHTTPClient(client.DefaultHTTPClientConfig())
		if err != nil {
			return nil, fmt.Errorf("failed to create HTTP client for provider %s: %w", p.Name, err)
		}

		providers = append(providers, &SMSProvider{
			Name:          p.Name,
			APIKey:        p.APIKey,
			APIURL:        p.APIURL,
			Weight:        p.Weight,
			MaxConcurrent: p.MaxConcurrent,
			httpClient:    httpClient,
		})
	}

	if len(providers) == 0 {
		return nil, fmt.Errorf("no SMS providers configured")
	}

	sc := &SMSClient{
		config:      cfg,
		providers:   providers,
		logger:      log.WithField("service", "sms_client"),
		rateLimiter: NewRateLimiter(cfg.RateLimit, time.Second),
	}

	log.Info("SMS client initialized", "providers_count", len(providers))

	return sc, nil
}

// GetNumber requests a phone number for the specified service
func (sc *SMSClient) GetNumber(ctx context.Context, service string) (*PhoneNumber, error) {
	// Apply rate limiting
	if err := sc.rateLimiter.Wait(ctx); err != nil {
		return nil, fmt.Errorf("rate limit exceeded: %w", err)
	}

	serviceCode := GetServiceCode(service)

	// Try providers with weighted round-robin
	var lastErr error
	for i := 0; i < len(sc.providers)*2; i++ {
		provider := sc.getNextProvider()
		
		// Check if provider is overloaded
		provider.mu.RLock()
		if provider.currentLoad >= provider.MaxConcurrent {
			provider.mu.RUnlock()
			continue
		}
		provider.currentLoad++
		provider.mu.RUnlock()

		number, err := sc.requestNumberFromProvider(ctx, provider, serviceCode)
		
		provider.mu.Lock()
		provider.currentLoad--
		provider.mu.Unlock()

		if err == nil {
			// Cache the number
			sc.cache.Store(number.ID, number)
			return number, nil
		}

		lastErr = err
		sc.logger.Warn("provider failed", "provider", provider.Name, "error", err)
	}

	return nil, fmt.Errorf("all providers failed: %w", lastErr)
}

// requestNumberFromProvider requests a number from a specific provider
func (sc *SMSClient) requestNumberFromProvider(ctx context.Context, provider *SMSProvider, serviceCode string) (*PhoneNumber, error) {
	reqURL := fmt.Sprintf("%s?api_key=%s&action=getNumber&service=%s",
		provider.APIURL,
		provider.APIKey,
		serviceCode,
	)

	resp, err := provider.httpClient.Get(ctx, reqURL)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// Parse SMS-Activate response format: ACCESS_NUMBER:id:number
	responseStr := strings.TrimSpace(string(body))
	parts := strings.Split(responseStr, ":")
	
	if len(parts) < 3 || parts[0] != "ACCESS_NUMBER" {
		return nil, fmt.Errorf("invalid response: %s", responseStr)
	}

	id := parts[1]
	number := parts[2]

	// Extract country code from number
	country := "unknown"
	if len(number) > 2 && strings.HasPrefix(number, "+") {
		country = number[1:4]
	}

	return &PhoneNumber{
		ID:          id,
		Number:      number,
		Country:     country,
		Service:     serviceCode,
		Status:      NumberStatusPending,
		ActivatedAt: time.Now(),
		ExpiresAt:   time.Now().Add(20 * time.Minute), // Default SMS-Activate timeout
	}, nil
}

// WaitForSMS waits for SMS code to arrive
func (sc *SMSClient) WaitForSMS(ctx context.Context, number *PhoneNumber, timeout time.Duration) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return "", fmt.Errorf("timeout waiting for SMS")
		case <-ticker.C:
			code, err := sc.CheckSMS(ctx, number)
			if err != nil {
				return "", err
			}
			if code != "" {
				number.Status = NumberStatusReceived
				number.SMSCode = code
				return code, nil
			}
		}
	}
}

// CheckSMS checks if SMS has been received
func (sc *SMSClient) CheckSMS(ctx context.Context, number *PhoneNumber) (string, error) {
	provider := sc.providers[0] // Use first provider for status check

	reqURL := fmt.Sprintf("%s?api_key=%s&action=getStatus&id=%s",
		provider.APIURL,
		provider.APIKey,
		number.ID,
	)

	resp, err := provider.httpClient.Get(ctx, reqURL)
	if err != nil {
		return "", fmt.Errorf("status check failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response: %w", err)
	}

	responseStr := strings.TrimSpace(string(body))

	// Status responses: STATUS_OK:<code> or STATUS_WAIT_CODE
	if strings.HasPrefix(responseStr, "STATUS_OK:") {
		code := strings.TrimPrefix(responseStr, "STATUS_OK:")
		return code, nil
	}

	if responseStr == "STATUS_WAIT_CODE" {
		return "", nil
	}

	if responseStr == "STATUS_CANCEL" || responseStr == "STATUS_TIMEOUT" {
		return "", fmt.Errorf("number cancelled or timed out")
	}

	return "", fmt.Errorf("unexpected status: %s", responseStr)
}

// CancelNumber cancels a phone number rental
func (sc *SMSClient) CancelNumber(ctx context.Context, number *PhoneNumber) error {
	provider := sc.providers[0]

	reqURL := fmt.Sprintf("%s?api_key=%s&action=setStatus&status=8&id=%s",
		provider.APIURL,
		provider.APIKey,
		number.ID,
	)

	resp, err := provider.httpClient.Get(ctx, reqURL)
	if err != nil {
		return fmt.Errorf("cancel failed: %w", err)
	}
	defer resp.Body.Close()

	sc.cache.Delete(number.ID)
	number.Status = NumberStatusCancelled

	return nil
}

// getNextProvider returns the next provider using weighted round-robin
func (sc *SMSClient) getNextProvider() *SMSProvider {
	sc.mu.Lock()
	defer sc.mu.Unlock()

	if len(sc.providers) == 0 {
		return nil
	}

	// Simple round-robin for now
	sc.currentIdx = (sc.currentIdx + 1) % len(sc.providers)
	return sc.providers[sc.currentIdx]
}

// GetCachedNumber retrieves a cached number by ID
func (sc *SMSClient) GetCachedNumber(id string) (*PhoneNumber, bool) {
	if val, ok := sc.cache.Load(id); ok {
		if number, ok := val.(*PhoneNumber); ok {
			// Check if not expired
			if time.Now().Before(number.ExpiresAt) {
				return number, true
			}
			sc.cache.Delete(id)
		}
	}
	return nil, false
}

// GetStats returns SMS client statistics
func (sc *SMSClient) GetStats() map[string]interface{} {
	stats := make(map[string]interface{})
	
	sc.mu.RLock()
	stats["providers_count"] = len(sc.providers)
	stats["current_provider_idx"] = sc.currentIdx
	sc.mu.RUnlock()

	providerStats := make([]map[string]interface{}, 0, len(sc.providers))
	for _, p := range sc.providers {
		p.mu.RLock()
		providerStats = append(providerStats, map[string]interface{}{
			"name":           p.Name,
			"current_load":   p.currentLoad,
			"max_concurrent": p.MaxConcurrent,
		})
		p.mu.RUnlock()
	}
	stats["providers"] = providerStats

	cachedCount := 0
	sc.cache.Range(func(key, value interface{}) bool {
		cachedCount++
		return true
	})
	stats["cached_numbers"] = cachedCount

	return stats
}

// Close closes the SMS client and releases resources
func (sc *SMSClient) Close() {
	for _, p := range sc.providers {
		if p.httpClient != nil {
			p.httpClient.Close()
		}
	}
}

// Helper for JSON marshaling
type phoneNumberJSON struct {
	ID          string `json:"id"`
	Number      string `json:"number"`
	Country     string `json:"country"`
	Service     string `json:"service"`
	Status      string `json:"status"`
	SMSCode     string `json:"sms_code,omitempty"`
	ActivatedAt int64  `json:"activated_at"`
	ExpiresAt   int64  `json:"expires_at"`
}

// MarshalJSON implements json.Marshaler
func (p *PhoneNumber) MarshalJSON() ([]byte, error) {
	return json.Marshal(phoneNumberJSON{
		ID:          p.ID,
		Number:      p.Number,
		Country:     p.Country,
		Service:     p.Service,
		Status:      p.Status.String(),
		SMSCode:     p.SMSCode,
		ActivatedAt: p.ActivatedAt.Unix(),
		ExpiresAt:   p.ExpiresAt.Unix(),
	})
}

// UnmarshalJSON implements json.Unmarshaler
func (p *PhoneNumber) UnmarshalJSON(data []byte) error {
	var pj phoneNumberJSON
	if err := json.Unmarshal(data, &pj); err != nil {
		return err
	}

	*p = PhoneNumber{
		ID:          pj.ID,
		Number:      pj.Number,
		Country:     pj.Country,
		Service:     pj.Service,
		SMSCode:     pj.SMSCode,
		ActivatedAt: time.Unix(pj.ActivatedAt, 0),
		ExpiresAt:   time.Unix(pj.ExpiresAt, 0),
	}

	switch pj.Status {
	case "pending":
		p.Status = NumberStatusPending
	case "ready":
		p.Status = NumberStatusReady
	case "received":
		p.Status = NumberStatusReceived
	case "cancelled":
		p.Status = NumberStatusCancelled
	case "timeout":
		p.Status = NumberStatusTimeout
	default:
		p.Status = NumberStatusPending
	}

	return nil
}
