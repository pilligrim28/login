package proxy

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/massreg/massreg-go/internal/core/config"
	"github.com/massreg/massreg-go/internal/core/logger"
)

// ProxyStrategy represents the proxy selection strategy
type ProxyStrategy string

const (
	// StrategyRoundRobin uses round-robin selection
	StrategyRoundRobin ProxyStrategy = "round_robin"
	// StrategyLeastUsed selects the least used proxy
	StrategyLeastUsed ProxyStrategy = "least_used"
	// StrategyFastest selects the fastest responding proxy
	StrategyFastest ProxyStrategy = "fastest"
	// StrategyLeastFailed selects the proxy with fewest failures
	StrategyLeastFailed ProxyStrategy = "least_failed"
)

// ProxyInfo holds information about a proxy
type ProxyInfo struct {
	URL           string        `json:"url"`
	Host          string        `json:"host"`
	Port          int           `json:"port"`
	Country       string        `json:"country"`
	Type          string        `json:"type"` // http, https, socks4, socks5
	Username      string        `json:"username,omitempty"`
	Password      string        `json:"password,omitempty"`
	UsageCount    int64         `json:"usage_count"`
	FailureCount  int           `json:"failure_count"`
	AvgLatency    time.Duration `json:"avg_latency"`
	LastChecked   time.Time     `json:"last_checked"`
	IsAlive       bool          `json:"is_alive"`
	LastFailure   time.Time     `json:"last_failure,omitempty"`
	mu            sync.RWMutex
}

// ProxyManager manages a pool of proxies with health checking and rotation
type ProxyManager struct {
	config         config.ProxyConfig
	proxies        []*ProxyInfo
	currentIndex   int
	strategy       ProxyStrategy
	mu             sync.RWMutex
	healthCheckCtx context.Context
	healthCheckCancel context.CancelFunc
	logger         *logger.Logger
}

// NewProxyManager creates a new proxy manager
func NewProxyManager(cfg config.ProxyConfig, log *logger.Logger) (*ProxyManager, error) {
	if !cfg.Enabled {
		return &ProxyManager{
			config:  cfg,
			proxies: make([]*ProxyInfo, 0),
			logger:  log,
		}, nil
	}

	// Parse strategy
	strategy := StrategyRoundRobin
	switch strings.ToLower(cfg.Strategy) {
	case "least_used":
		strategy = StrategyLeastUsed
	case "fastest":
		strategy = StrategyFastest
	case "least_failed":
		strategy = StrategyLeastFailed
	}

	pm := &ProxyManager{
		config:   cfg,
		strategy: strategy,
		logger:   log.WithField("service", "proxy_manager"),
	}

	// Parse and add proxies
	for _, proxyURL := range cfg.Proxies {
		if err := pm.AddProxy(proxyURL); err != nil {
			log.Warn("failed to parse proxy", "error", err, "proxy", proxyURL)
		}
	}

	// Start health checker if enabled
	if cfg.HealthCheck.Enabled {
		pm.startHealthChecker()
	}

	log.Info("proxy manager initialized", "proxies_count", len(pm.proxies), "strategy", strategy)

	return pm, nil
}

// AddProxy adds a proxy to the pool
func (pm *ProxyManager) AddProxy(proxyURL string) error {
	info, err := pm.parseProxyURL(proxyURL)
	if err != nil {
		return err
	}

	pm.mu.Lock()
	defer pm.mu.Unlock()

	pm.proxies = append(pm.proxies, info)
	return nil
}

// parseProxyURL parses a proxy URL into ProxyInfo
func (pm *ProxyManager) parseProxyURL(proxyURL string) (*ProxyInfo, error) {
	u, err := url.Parse(proxyURL)
	if err != nil {
		return nil, fmt.Errorf("invalid proxy URL: %w", err)
	}

	host, portStr, err := net.SplitHostPort(u.Host)
	if err != nil {
		host = u.Host
		portStr = "80"
	}

	port := 80
	if portStr != "" {
		fmt.Sscanf(portStr, "%d", &port)
	}

	proxyType := "http"
	if u.Scheme != "" {
		proxyType = u.Scheme
	}

	var username, password string
	if u.User != nil {
		username = u.User.Username()
		password, _ = u.User.Password()
	}

	return &ProxyInfo{
		URL:         proxyURL,
		Host:        host,
		Port:        port,
		Type:        proxyType,
		Username:    username,
		Password:    password,
		IsAlive:     true,
		LastChecked: time.Now(),
	}, nil
}

// GetProxy returns the next available proxy based on the strategy
func (pm *ProxyManager) GetProxy(ctx context.Context) (*ProxyInfo, error) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	if len(pm.proxies) == 0 {
		return nil, nil // No proxies configured, return nil (direct connection)
	}

	var selected *ProxyInfo

	switch pm.strategy {
	case StrategyRoundRobin:
		selected = pm.getRoundRobin()
	case StrategyLeastUsed:
		selected = pm.getLeastUsed()
	case StrategyFastest:
		selected = pm.getFastest()
	case StrategyLeastFailed:
		selected = pm.getLeastFailed()
	}

	if selected != nil && selected.IsAlive {
		selected.mu.Lock()
		selected.UsageCount++
		selected.mu.Unlock()
		return selected, nil
	}

	// Fallback: return any alive proxy
	for _, p := range pm.proxies {
		if p.IsAlive {
			p.mu.Lock()
			p.UsageCount++
			p.mu.Unlock()
			return p, nil
		}
	}

	return nil, fmt.Errorf("no healthy proxies available")
}

// getRoundRobin returns the next proxy in round-robin fashion
func (pm *ProxyManager) getRoundRobin() *ProxyInfo {
	if len(pm.proxies) == 0 {
		return nil
	}

	pm.currentIndex = (pm.currentIndex + 1) % len(pm.proxies)
	return pm.proxies[pm.currentIndex]
}

// getLeastUsed returns the proxy with the lowest usage count
func (pm *ProxyManager) getLeastUsed() *ProxyInfo {
	var selected *ProxyInfo
	minUsage := int64(-1)

	for _, p := range pm.proxies {
		if !p.IsAlive {
			continue
		}
		p.mu.RLock()
		usage := p.UsageCount
		p.mu.RUnlock()

		if minUsage == -1 || usage < minUsage {
			minUsage = usage
			selected = p
		}
	}

	return selected
}

// getFastest returns the proxy with the lowest average latency
func (pm *ProxyManager) getFastest() *ProxyInfo {
	var selected *ProxyInfo
	minLatency := time.Duration(-1)

	for _, p := range pm.proxies {
		if !p.IsAlive {
			continue
		}
		p.mu.RLock()
		latency := p.AvgLatency
		p.mu.RUnlock()

		if latency > 0 && (minLatency == -1 || latency < minLatency) {
			minLatency = latency
			selected = p
		}
	}

	return selected
}

// getLeastFailed returns the proxy with the fewest failures
func (pm *ProxyManager) getLeastFailed() *ProxyInfo {
	var selected *ProxyInfo
	minFailures := -1

	for _, p := range pm.proxies {
		if !p.IsAlive {
			continue
		}
		p.mu.RLock()
		failures := p.FailureCount
		p.mu.RUnlock()

		if minFailures == -1 || failures < minFailures {
			minFailures = failures
			selected = p
		}
	}

	return selected
}

// MarkSuccess marks a proxy as successful
func (pm *ProxyManager) MarkSuccess(proxy *ProxyInfo, latency time.Duration) {
	if proxy == nil {
		return
	}

	proxy.mu.Lock()
	defer proxy.mu.Unlock()

	// Update average latency
	if proxy.AvgLatency == 0 {
		proxy.AvgLatency = latency
	} else {
		proxy.AvgLatency = (proxy.AvgLatency*9 + latency) / 10
	}

	proxy.IsAlive = true
	proxy.LastChecked = time.Now()
}

// MarkFailure marks a proxy as failed
func (pm *ProxyManager) MarkFailure(proxy *ProxyInfo) {
	if proxy == nil {
		return
	}

	proxy.mu.Lock()
	defer proxy.mu.Unlock()

	proxy.FailureCount++
	proxy.LastFailure = time.Now()

	// Check if proxy should be marked as dead
	if proxy.FailureCount >= pm.config.HealthCheck.DeadThreshold {
		proxy.IsAlive = false
		pm.logger.Warn("proxy marked as dead", "proxy", proxy.URL, "failures", proxy.FailureCount)
	}
}

// startHealthChecker starts the background health check process
func (pm *ProxyManager) startHealthChecker() {
	pm.healthCheckCtx, pm.healthCheckCancel = context.WithCancel(context.Background())

	go func() {
		ticker := time.NewTicker(pm.config.HealthCheck.Interval)
		defer ticker.Stop()

		for {
			select {
			case <-pm.healthCheckCtx.Done():
				return
			case <-ticker.C:
				pm.checkHealth()
			}
		}
	}()
}

// checkHealth checks the health of all proxies
func (pm *ProxyManager) checkHealth() {
	pm.mu.RLock()
	proxies := make([]*ProxyInfo, len(pm.proxies))
	copy(proxies, pm.proxies)
	pm.mu.RUnlock()

	for _, proxy := range proxies {
		go pm.checkSingleProxy(proxy)
	}
}

// checkSingleProxy checks the health of a single proxy
func (pm *ProxyManager) checkSingleProxy(proxy *ProxyInfo) {
	startTime := time.Now()

	// Try to connect to the proxy
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("%s:%d", proxy.Host, proxy.Port), pm.config.HealthCheck.Timeout)
	if err != nil {
		pm.MarkFailure(proxy)
		return
	}
	conn.Close()

	latency := time.Since(startTime)
	pm.MarkSuccess(proxy, latency)

	// Attempt recovery for dead proxies
	if !proxy.IsAlive && time.Since(proxy.LastFailure) > pm.config.HealthCheck.RecoveryInterval {
		proxy.mu.Lock()
		proxy.IsAlive = true
		proxy.FailureCount = 0
		proxy.mu.Unlock()
		pm.logger.Info("proxy recovered", "proxy", proxy.URL)
	}
}

// Stop stops the proxy manager and health checker
func (pm *ProxyManager) Stop() {
	if pm.healthCheckCancel != nil {
		pm.healthCheckCancel()
	}
}

// GetStats returns proxy pool statistics
func (pm *ProxyManager) GetStats() map[string]interface{} {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	total := len(pm.proxies)
	alive := 0
	totalUsage := int64(0)
	totalFailures := 0

	for _, p := range pm.proxies {
		p.mu.RLock()
		if p.IsAlive {
			alive++
		}
		totalUsage += p.UsageCount
		totalFailures += p.FailureCount
		p.mu.RUnlock()
	}

	return map[string]interface{}{
		"total_proxies":    total,
		"alive_proxies":    alive,
		"dead_proxies":     total - alive,
		"total_usage":      totalUsage,
		"total_failures":   totalFailures,
		"strategy":         string(pm.strategy),
	}
}

// GetProxyURL returns the full proxy URL for use with HTTP clients
func (p *ProxyInfo) GetProxyURL() *url.URL {
	scheme := "http"
	if p.Type == "https" {
		scheme = "https"
	} else if strings.HasPrefix(p.Type, "socks") {
		scheme = p.Type
	}

	var user *url.Userinfo
	if p.Username != "" {
		if p.Password != "" {
			user = url.UserPassword(p.Username, p.Password)
		} else {
			user = url.User(p.Username)
		}
	}

	return &url.URL{
		Scheme: scheme,
		User:   user,
		Host:   fmt.Sprintf("%s:%d", p.Host, p.Port),
	}
}
