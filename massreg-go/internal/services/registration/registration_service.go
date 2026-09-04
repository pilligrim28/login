package registration

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/massreg/massreg-go/internal/core/config"
	"github.com/massreg/massreg-go/internal/core/logger"
	"github.com/massreg/massreg-go/internal/services/proxy"
	"github.com/massreg/massreg-go/internal/services/sms"
	"github.com/massreg/massreg-go/pkg/client"
)

// ServiceType represents supported registration services
type ServiceType string

const (
	ServiceMicrosoft  ServiceType = "Microsoft"
	ServiceGoogle     ServiceType = "Google"
	ServiceApple      ServiceType = "Apple"
	ServiceSnapchat   ServiceType = "Snapchat"
	ServiceInstagram  ServiceType = "Instagram"
	ServiceFacebook   ServiceType = "Facebook"
	ServiceDiscord    ServiceType = "Discord"
)

// RegistrationResult holds the result of a registration attempt
type RegistrationResult struct {
	Success       bool              `json:"success"`
	Service       ServiceType       `json:"service"`
	Email         string            `json:"email"`
	Password      string            `json:"password,omitempty"`
	PhoneNumber   string            `json:"phone_number,omitempty"`
	Country       string            `json:"country,omitempty"`
	ProxyUsed     string            `json:"proxy_used,omitempty"`
	ErrorCode     string            `json:"error_code,omitempty"`
	ErrorMessage  string            `json:"error_message,omitempty"`
	Duration      time.Duration     `json:"duration_ms"`
	Timestamp     time.Time         `json:"timestamp"`
	Metadata      map[string]string `json:"metadata,omitempty"`
}

// RegistrationRequest holds parameters for registration
type RegistrationRequest struct {
	Service       ServiceType `json:"service"`
	Email         string      `json:"email,omitempty"`
	Password      string      `json:"password,omitempty"`
	FirstName     string      `json:"first_name,omitempty"`
	LastName      string      `json:"last_name,omitempty"`
	Country       string      `json:"country"`
	NeedPhone     bool        `json:"need_phone"`
	NeedSMS       bool        `json:"need_sms"`
	ProxyRequired bool        `json:"proxy_required"`
}

// BrowserFingerprint emulates browser headers and fingerprints
type BrowserFingerprint struct {
	UserAgent      string
	AcceptLanguage string
	AcceptEncoding string
	Referer        string
	Origin         string
	DNT            string
	SecCHUA        string
	SecCHUAMobile  string
	SecCHUAPlatform string
}

// RegistrationService handles account registration without browser automation
type RegistrationService struct {
	config      config.ServicesConfig
	httpClient  *client.HTTPClient
	proxyMgr    *proxy.ProxyManager
	smsClient   *sms.SMSClient
	logger      *logger.Logger
	fingerprints map[ServiceType]*BrowserFingerprint
	
	// Metrics
	mu                sync.RWMutex
	totalAttempts     int64
	successCount      int64
	failCount         int64
	avgDuration       time.Duration
	serviceStats      map[ServiceType]*serviceStats
}

type serviceStats struct {
	attempts   int64
	successes  int64
	failures   int64
	lastError  string
}

// NewRegistrationService creates a new registration service
func NewRegistrationService(
	cfg config.ServicesConfig,
	proxyMgr *proxy.ProxyManager,
	smsClient *sms.SMSClient,
	log *logger.Logger,
) (*RegistrationService, error) {
	httpClient, err := client.NewHTTPClient(client.DefaultHTTPClientConfig())
	if err != nil {
		return nil, fmt.Errorf("failed to create HTTP client: %w", err)
	}

	rs := &RegistrationService{
		config:      cfg,
		httpClient:  httpClient,
		proxyMgr:    proxyMgr,
		smsClient:   smsClient,
		logger:      log.WithField("service", "registration"),
		fingerprints: make(map[ServiceType]*BrowserFingerprint),
		serviceStats: make(map[ServiceType]*serviceStats),
	}

	// Initialize browser fingerprints for each service
	rs.initFingerprints()

	return rs, nil
}

// initFingerprints initializes browser fingerprints for each service
func (rs *RegistrationService) initFingerprints() {
	// Microsoft Outlook fingerprint
	rs.fingerprints[ServiceMicrosoft] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://signup.live.com/",
		Origin:         "https://signup.live.com",
		DNT:            "1",
		SecCHUA:        `"Not A(Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"`,
		SecCHUAMobile:  "?0",
		SecCHUAPlatform: `"Windows"`,
	}

	// Google Gmail fingerprint
	rs.fingerprints[ServiceGoogle] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://accounts.google.com/signup/v2/webcreateaccount",
		Origin:         "https://accounts.google.com",
		DNT:            "1",
		SecCHUA:        `"Not A(Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"`,
		SecCHUAMobile:  "?0",
		SecCHUAPlatform: `"Windows"`,
	}

	// Apple ID fingerprint
	rs.fingerprints[ServiceApple] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://appleid.apple.com/account/create",
		Origin:         "https://appleid.apple.com",
		DNT:            "1",
	}

	// Snapchat fingerprint
	rs.fingerprints[ServiceSnapchat] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://accounts.snapchat.com/accounts/signup",
		Origin:         "https://accounts.snapchat.com",
	}

	// Instagram fingerprint
	rs.fingerprints[ServiceInstagram] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://www.instagram.com/accounts/emailsignup/",
		Origin:         "https://www.instagram.com",
	}

	// Facebook fingerprint
	rs.fingerprints[ServiceFacebook] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://www.facebook.com/r.php",
		Origin:         "https://www.facebook.com",
	}

	// Discord fingerprint
	rs.fingerprints[ServiceDiscord] = &BrowserFingerprint{
		UserAgent:      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9",
		AcceptEncoding: "gzip, deflate, br",
		Referer:        "https://discord.com/register",
		Origin:         "https://discord.com",
	}
}

// Register performs account registration for the specified service
func (rs *RegistrationService) Register(ctx context.Context, req *RegistrationRequest) (*RegistrationResult, error) {
	startTime := time.Now()

	rs.mu.Lock()
	rs.totalAttempts++
	rs.mu.Unlock()

	// Get proxy if required
	var proxyInfo *proxy.ProxyInfo
	var err error
	if req.ProxyRequired {
		proxyInfo, err = rs.proxyMgr.GetProxy(ctx)
		if err != nil {
			return rs.createFailureResult(req, "", "proxy_error", err.Error(), startTime)
		}
	}

	// Generate credentials if not provided
	if req.Email == "" {
		req.Email = rs.generateEmail()
	}
	if req.Password == "" {
		req.Password = rs.generatePassword()
	}

	// Get phone number if needed
	var phoneNumber *sms.PhoneNumber
	if req.NeedPhone || req.NeedSMS {
		phoneNumber, err = rs.smsClient.GetNumber(ctx, string(req.Service))
		if err != nil {
			return rs.createFailureResult(req, "", "sms_error", err.Error(), startTime)
		}
		defer func() {
			if phoneNumber.Status != sms.NumberStatusReceived {
				rs.smsClient.CancelNumber(context.Background(), phoneNumber)
			}
		}()
	}

	// Perform service-specific registration
	var result *RegistrationResult
	switch req.Service {
	case ServiceMicrosoft:
		result, err = rs.registerMicrosoft(ctx, req, proxyInfo, phoneNumber)
	case ServiceGoogle:
		result, err = rs.registerGoogle(ctx, req, proxyInfo, phoneNumber)
	case ServiceApple:
		result, err = rs.registerApple(ctx, req, proxyInfo, phoneNumber)
	case ServiceSnapchat:
		result, err = rs.registerSnapchat(ctx, req, proxyInfo, phoneNumber)
	case ServiceInstagram:
		result, err = rs.registerInstagram(ctx, req, proxyInfo, phoneNumber)
	case ServiceFacebook:
		result, err = rs.registerFacebook(ctx, req, proxyInfo, phoneNumber)
	case ServiceDiscord:
		result, err = rs.registerDiscord(ctx, req, proxyInfo, phoneNumber)
	default:
		err = fmt.Errorf("unsupported service: %s", req.Service)
	}

	if err != nil {
		rs.mu.Lock()
		rs.failCount++
		rs.serviceStats[req.Service].failures++
		rs.serviceStats[req.Service].lastError = err.Error()
		rs.mu.Unlock()

		if proxyInfo != nil {
			rs.proxyMgr.MarkFailure(proxyInfo)
		}

		return rs.createFailureResult(req, req.Email, "registration_error", err.Error(), startTime)
	}

	// Update metrics
	rs.mu.Lock()
	rs.successCount++
	rs.serviceStats[req.Service].successes++
	duration := time.Since(startTime)
	rs.avgDuration = (rs.avgDuration*time.Duration(rs.successCount-1) + duration) / time.Duration(rs.successCount)
	rs.mu.Unlock()

	if proxyInfo != nil {
		rs.proxyMgr.MarkSuccess(proxyInfo, duration)
	}

	return result, nil
}

// registerMicrosoft registers a Microsoft/Outlook account
func (rs *RegistrationService) registerMicrosoft(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	fingerprint := rs.fingerprints[ServiceMicrosoft]
	
	// Step 1: Get session token
	sessionURL := "https://signup.live.com/API/Signup?uaid=&ppft="
	sessionReq, err := http.NewRequestWithContext(ctx, http.MethodGet, sessionURL, nil)
	if err != nil {
		return nil, err
	}
	rs.applyFingerprint(sessionReq, fingerprint)

	resp, err := rs.httpClient.Do(ctx, sessionReq)
	if err != nil {
		return nil, fmt.Errorf("failed to get session: %w", err)
	}
	defer resp.Body.Close()

	// Step 2: Create account
	createURL := "https://signup.live.com/API/Signup"
	payload := map[string]interface{}{
		"emailAddress": req.Email,
		"password":     req.Password,
		"country":      req.Country,
		"firstName":    req.FirstName,
		"lastName":     req.LastName,
	}

	if phoneNumber != nil {
		payload["phoneNumber"] = phoneNumber.Number
	}

	jsonData, _ := json.Marshal(payload)
	createReq, err := http.NewRequestWithContext(ctx, http.MethodPost, createURL, bytes.NewReader(jsonData))
	if err != nil {
		return nil, err
	}
	rs.applyFingerprint(createReq, fingerprint)
	createReq.Header.Set("Content-Type", "application/json")

	resp, err = rs.httpClient.Do(ctx, createReq)
	if err != nil {
		return nil, fmt.Errorf("failed to create account: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registration failed with status %d: %s", resp.StatusCode, string(body))
	}

	return &RegistrationResult{
		Success:     true,
		Service:     req.Service,
		Email:       req.Email,
		Password:    req.Password,
		PhoneNumber: req.Email, // Microsoft uses email as primary identifier
		Country:     req.Country,
		ProxyUsed:   proxyInfo.URL,
		Duration:    time.Since(startTime),
		Timestamp:   time.Now(),
	}, nil
}

// registerGoogle registers a Google/Gmail account
func (rs *RegistrationService) registerGoogle(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	fingerprint := rs.fingerprints[ServiceGoogle]
	
	// Google signup endpoint
	signupURL := "https://accounts.google.com/_/signup/accountdetails"
	
	payload := map[string]interface{}{
		"email":        req.Email,
		"password":     req.Password,
		"firstName":    req.FirstName,
		"lastName":     req.LastName,
		"country":      req.Country,
	}

	jsonData, _ := json.Marshal(payload)
	createReq, err := http.NewRequestWithContext(ctx, http.MethodPost, signupURL, bytes.NewReader(jsonData))
	if err != nil {
		return nil, err
	}
	rs.applyFingerprint(createReq, fingerprint)
	createReq.Header.Set("Content-Type", "application/json")

	resp, err := rs.httpClient.Do(ctx, createReq)
	if err != nil {
		return nil, fmt.Errorf("failed to create Google account: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("Google registration failed: %s", string(body))
	}

	return &RegistrationResult{
		Success:     true,
		Service:     req.Service,
		Email:       req.Email,
		Password:    req.Password,
		Country:     req.Country,
		ProxyUsed:   proxyInfo.URL,
		Duration:    time.Since(startTime),
		Timestamp:   time.Now(),
	}, nil
}

// registerApple registers an Apple ID account
func (rs *RegistrationService) registerApple(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	fingerprint := rs.fingerprints[ServiceApple]
	
	createURL := "https://appleid.apple.com/account/create"
	
	payload := map[string]interface{}{
		"email":       req.Email,
		"password":    req.Password,
		"firstName":   req.FirstName,
		"lastName":    req.LastName,
		"country":     req.Country,
	}

	jsonData, _ := json.Marshal(payload)
	createReq, err := http.NewRequestWithContext(ctx, http.MethodPost, createURL, bytes.NewReader(jsonData))
	if err != nil {
		return nil, err
	}
	rs.applyFingerprint(createReq, fingerprint)
	createReq.Header.Set("Content-Type", "application/json")

	resp, err := rs.httpClient.Do(ctx, createReq)
	if err != nil {
		return nil, fmt.Errorf("failed to create Apple ID: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("Apple registration failed: %s", string(body))
	}

	return &RegistrationResult{
		Success:     true,
		Service:     req.Service,
		Email:       req.Email,
		Password:    req.Password,
		Country:     req.Country,
		ProxyUsed:   proxyInfo.URL,
		Duration:    time.Since(startTime),
		Timestamp:   time.Now(),
	}, nil
}

// Placeholder implementations for other services
func (rs *RegistrationService) registerSnapchat(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	return rs.genericRegister(ctx, req, proxyInfo, phoneNumber, "https://accounts.snapchat.com/accounts/signup")
}

func (rs *RegistrationService) registerInstagram(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	return rs.genericRegister(ctx, req, proxyInfo, phoneNumber, "https://www.instagram.com/accounts/emailsignup/")
}

func (rs *RegistrationService) registerFacebook(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	return rs.genericRegister(ctx, req, proxyInfo, phoneNumber, "https://www.facebook.com/r.php")
}

func (rs *RegistrationService) registerDiscord(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber) (*RegistrationResult, error) {
	return rs.genericRegister(ctx, req, proxyInfo, phoneNumber, "https://discord.com/api/v9/auth/register")
}

// genericRegister is a helper for simple registration endpoints
func (rs *RegistrationService) genericRegister(ctx context.Context, req *RegistrationRequest, proxyInfo *proxy.ProxyInfo, phoneNumber *sms.PhoneNumber, apiURL string) (*RegistrationResult, error) {
	fingerprint := rs.fingerprints[req.Service]
	
	payload := map[string]interface{}{
		"email":    req.Email,
		"password": req.Password,
		"username": strings.Split(req.Email, "@")[0],
	}

	if phoneNumber != nil {
		payload["phone"] = phoneNumber.Number
	}

	jsonData, _ := json.Marshal(payload)
	createReq, err := http.NewRequestWithContext(ctx, http.MethodPost, apiURL, bytes.NewReader(jsonData))
	if err != nil {
		return nil, err
	}
	rs.applyFingerprint(createReq, fingerprint)
	createReq.Header.Set("Content-Type", "application/json")

	resp, err := rs.httpClient.Do(ctx, createReq)
	if err != nil {
		return nil, fmt.Errorf("registration failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registration failed with status %d: %s", resp.StatusCode, string(body))
	}

	return &RegistrationResult{
		Success:     true,
		Service:     req.Service,
		Email:       req.Email,
		Password:    req.Password,
		Country:     req.Country,
		ProxyUsed:   proxyInfo.URL,
		Duration:    time.Since(startTime),
		Timestamp:   time.Now(),
	}, nil
}

// applyFingerprint applies browser fingerprint headers to request
func (rs *RegistrationService) applyFingerprint(req *http.Request, fp *BrowserFingerprint) {
	req.Header.Set("User-Agent", fp.UserAgent)
	req.Header.Set("Accept-Language", fp.AcceptLanguage)
	req.Header.Set("Accept-Encoding", fp.AcceptEncoding)
	if fp.Referer != "" {
		req.Header.Set("Referer", fp.Referer)
	}
	if fp.Origin != "" {
		req.Header.Set("Origin", fp.Origin)
	}
	if fp.DNT != "" {
		req.Header.Set("DNT", fp.DNT)
	}
	if fp.SecCHUA != "" {
		req.Header.Set("Sec-CH-UA", fp.SecCHUA)
	}
	if fp.SecCHUAMobile != "" {
		req.Header.Set("Sec-CH-UA-Mobile", fp.SecCHUAMobile)
	}
	if fp.SecCHUAPlatform != "" {
		req.Header.Set("Sec-CH-UA-Platform", fp.SecCHUAPlatform)
	}
}

// generateEmail generates a random email address
func (rs *RegistrationService) generateEmail() string {
	const chars = "abcdefghijklmnopqrstuvwxyz0123456789"
	domains := []string{"outlook.com", "gmail.com", "proton.me", "tutanota.com"}

	b := make([]byte, 12)
	rand.Read(b)
	username := hex.EncodeToString(b)[:10]

	domain := domains[time.Now().UnixNano()%int64(len(domains))]
	return fmt.Sprintf("%s@%s", username, domain)
}

// generatePassword generates a strong random password
func (rs *RegistrationService) generatePassword() string {
	const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
	b := make([]byte, 16)
	rand.Read(b)
	
	for i := range b {
		b[i] = chars[int(b[i])%len(chars)]
	}
	return string(b)
}

// createFailureResult creates a failure result
func (rs *RegistrationService) createFailureResult(req *RegistrationRequest, email, errorCode, errorMessage string, startTime time.Time) *RegistrationResult {
	return &RegistrationResult{
		Success:      false,
		Service:      req.Service,
		Email:        email,
		ErrorCode:    errorCode,
		ErrorMessage: errorMessage,
		Duration:     time.Since(startTime),
		Timestamp:    time.Now(),
	}
}

// GetStats returns registration service statistics
func (rs *RegistrationService) GetStats() map[string]interface{} {
	rs.mu.RLock()
	defer rs.mu.RUnlock()

	serviceDetails := make(map[string]interface{})
	for service, stats := range rs.serviceStats {
		serviceDetails[string(service)] = map[string]interface{}{
			"attempts":   stats.attempts,
			"successes":  stats.successes,
			"failures":   stats.failures,
			"last_error": stats.lastError,
		}
	}

	successRate := float64(0)
	if rs.totalAttempts > 0 {
		successRate = float64(rs.successCount) / float64(rs.totalAttempts) * 100
	}

	return map[string]interface{}{
		"total_attempts":  rs.totalAttempts,
		"success_count":   rs.successCount,
		"fail_count":      rs.failCount,
		"success_rate":    successRate,
		"avg_duration_ms": rs.avgDuration.Milliseconds(),
		"services":        serviceDetails,
	}
}

// Close closes the registration service
func (rs *RegistrationService) Close() {
	if rs.httpClient != nil {
		rs.httpClient.Close()
	}
}

// Helper variable for startTime in results
var startTime = time.Now()
