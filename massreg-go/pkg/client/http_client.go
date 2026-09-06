package client

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"sync"
	"time"

	"github.com/klauspost/compress/zstd"
	"github.com/valyala/fasthttp"
)

// CompressionType represents the compression algorithm used
type CompressionType string

const (
	// CompressionGzip uses gzip compression
	CompressionGzip CompressionType = "gzip"
	// CompressionZstd uses zstd compression
	CompressionZstd CompressionType = "zstd"
	// CompressionNone uses no compression
	CompressionNone CompressionType = "none"
)

// HTTPClientConfig holds configuration for the optimized HTTP client
type HTTPClientConfig struct {
	MaxConnsPerHost       int
	MaxIdleConns          int
	MaxIdleConnsPerHost   int
	IdleConnTimeout       time.Duration
	DialTimeout           time.Duration
	ReadTimeout           time.Duration
	WriteTimeout          time.Duration
	TLSHandshakeTimeout   time.Duration
	ExpectContinueTimeout time.Duration
	ResponseHeaderTimeout time.Duration
	DisableCompression    bool
	CompressionType       CompressionType
	ProxyURL              *url.URL
	EnableHTTP2           bool
	MaxRetries            int
	InitialRetryDelay     time.Duration
	MaxRetryDelay         time.Duration
	UserAgent             string
}

// DefaultHTTPClientConfig returns default HTTP client configuration
func DefaultHTTPClientConfig() HTTPClientConfig {
	return HTTPClientConfig{
		MaxConnsPerHost:       100,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   10,
		IdleConnTimeout:       90 * time.Second,
		DialTimeout:           30 * time.Second,
		ReadTimeout:           30 * time.Second,
		WriteTimeout:          30 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
		ResponseHeaderTimeout: 10 * time.Second,
		DisableCompression:    false,
		CompressionType:       CompressionGzip,
		EnableHTTP2:           true,
		MaxRetries:            3,
		InitialRetryDelay:     100 * time.Millisecond,
		MaxRetryDelay:         10 * time.Second,
		UserAgent:             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
	}
}

// Metrics holds HTTP client metrics
type Metrics struct {
	mu                sync.RWMutex
	RequestsTotal     int64
	RequestsSuccess   int64
	RequestsFailed    int64
	BytesSent         int64
	BytesReceived     int64
	CompressionRatio  float64
	AverageLatency    time.Duration
	RetryCount        int64
	ConnectionsActive int64
}

// HTTPClient is an optimized HTTP client with compression and connection pooling
type HTTPClient struct {
	config     HTTPClientConfig
	client     *fasthttp.Client
	metrics    *Metrics
	zstdEnc   *zstd.Encoder
	zstdDec   *zstd.Decoder
	transport  *http.Transport
	stdClient *http.Client
}

// NewHTTPClient creates a new optimized HTTP client
func NewHTTPClient(cfg HTTPClientConfig) (*HTTPClient, error) {
	// Create fasthttp client for high performance
	fastClient := &fasthttp.Client{
		MaxConnsPerHost:            cfg.MaxConnsPerHost,
		MaxIdleConnDuration:        cfg.IdleConnTimeout,
		ReadTimeout:                cfg.ReadTimeout,
		WriteTimeout:               cfg.WriteTimeout,
		Dial:                       fasthttDialer(cfg.DialTimeout),
		NoDefaultUserAgentHeader:   true,
	}

	// Create zstd encoder/decoder
	zstdEnc, err := zstd.NewWriter(nil, zstd.WithEncoderLevel(zstd.SpeedFastest))
	if err != nil {
		return nil, fmt.Errorf("failed to create zstd encoder: %w", err)
	}

	zstdDec, err := zstd.NewReader(nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create zstd decoder: %w", err)
	}

	// Create standard HTTP client for fallback
	transport := &http.Transport{
		Proxy:                 http.ProxyURL(cfg.ProxyURL),
		DialContext:           (&net.Dialer{Timeout: cfg.DialTimeout}).DialContext,
		ForceAttemptHTTP2:     cfg.EnableHTTP2,
		MaxIdleConns:          cfg.MaxIdleConns,
		MaxIdleConnsPerHost:   cfg.MaxIdleConnsPerHost,
		IdleConnTimeout:       cfg.IdleConnTimeout,
		TLSHandshakeTimeout:   cfg.TLSHandshakeTimeout,
		ExpectContinueTimeout: cfg.ExpectContinueTimeout,
		ResponseHeaderTimeout: cfg.ResponseHeaderTimeout,
		DisableCompression:    true, // We handle compression manually
		TLSClientConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
		},
	}

	stdClient := &http.Client{
		Transport: transport,
		Timeout:   cfg.ReadTimeout + cfg.WriteTimeout,
	}

	return &HTTPClient{
		config:     cfg,
		client:     fastClient,
		metrics:    &Metrics{},
		zstdEnc:    zstdEnc,
		zstdDec:    zstdDec,
		transport:  transport,
		stdClient:  stdClient,
	}, nil
}

// fasthttDialer creates a fasthttp dialer with timeout
func fasthttDialer(timeout time.Duration) fasthttp.DialFunc {
	return func(addr string) (net.Conn, error) {
		return net.DialTimeout("tcp", addr, timeout)
	}
}

// Do executes an HTTP request with retry logic and compression
func (c *HTTPClient) Do(ctx context.Context, req *http.Request) (*http.Response, error) {
	var (
		resp *http.Response
		err  error
	)

	for attempt := 0; attempt <= c.config.MaxRetries; attempt++ {
		resp, err = c.doWithCompression(ctx, req)
		if err == nil {
			break
		}

		if attempt < c.config.MaxRetries {
			delay := c.calculateRetryDelay(attempt)
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(delay):
			}

			c.metrics.mu.Lock()
			c.metrics.RetryCount++
			c.metrics.mu.Unlock()
		}
	}

	return resp, err
}

// doWithCompression executes request with optional compression
func (c *HTTPClient) doWithCompression(ctx context.Context, req *http.Request) (*http.Response, error) {
	startTime := time.Now()

	// Add user agent if not set
	if req.Header.Get("User-Agent") == "" {
		req.Header.Set("User-Agent", c.config.UserAgent)
	}

	// Compress request body if needed
	if req.Body != nil && !c.config.DisableCompression {
		bodyBytes, err := io.ReadAll(req.Body)
		if err != nil {
			return nil, fmt.Errorf("failed to read request body: %w", err)
		}
		req.Body.Close()

		if len(bodyBytes) > 1024 { // Only compress if body > 1KB
			var compressed []byte
			switch c.config.CompressionType {
			case CompressionGzip:
				compressed, err = c.gzipCompress(bodyBytes)
			case CompressionZstd:
				compressed, err = c.zstdCompress(bodyBytes)
			default:
				compressed = bodyBytes
			}

			if err == nil && len(compressed) < len(bodyBytes) {
				req.Body = io.NopCloser(bytes.NewReader(compressed))
				req.ContentLength = int64(len(compressed))
				
				if c.config.CompressionType == CompressionGzip {
					req.Header.Set("Content-Encoding", "gzip")
				} else if c.config.CompressionType == CompressionZstd {
					req.Header.Set("Content-Encoding", "zstd")
				}

				c.metrics.mu.Lock()
				c.metrics.BytesSent += int64(len(compressed))
				c.metrics.CompressionRatio = float64(len(compressed)) / float64(len(bodyBytes))
				c.metrics.mu.Unlock()
			} else {
				req.Body = io.NopCloser(bytes.NewReader(bodyBytes))
				c.metrics.mu.Lock()
				c.metrics.BytesSent += int64(len(bodyBytes))
				c.metrics.mu.Unlock()
			}
		} else {
			req.Body = io.NopCloser(bytes.NewReader(bodyBytes))
			c.metrics.mu.Lock()
			c.metrics.BytesSent += int64(len(bodyBytes))
			c.metrics.mu.Unlock()
		}
	}

	// Execute request
	resp, err := c.stdClient.Do(req.WithContext(ctx))
	if err != nil {
		c.metrics.mu.Lock()
		c.metrics.RequestsFailed++
		c.metrics.mu.Unlock()
		return nil, err
	}

	// Read and decompress response if needed
	var responseBody []byte
	if resp.Body != nil {
		responseBody, err = io.ReadAll(resp.Body)
		resp.Body.Close()

		if err == nil {
			encoding := resp.Header.Get("Content-Encoding")
			switch encoding {
			case "gzip":
				responseBody, err = c.gzipDecompress(responseBody)
			case "zstd":
				responseBody, err = c.zstdDecompress(responseBody)
			}

			if err == nil {
				resp.Body = io.NopCloser(bytes.NewReader(responseBody))
				c.metrics.mu.Lock()
				c.metrics.BytesReceived += int64(len(responseBody))
				c.metrics.RequestsSuccess++
				c.metrics.mu.Unlock()
			}
		}
	}

	// Update metrics
	c.metrics.mu.Lock()
	c.metrics.RequestsTotal++
	latency := time.Since(startTime)
	c.metrics.AverageLatency = (c.metrics.AverageLatency*time.Duration(c.metrics.RequestsTotal-1) + latency) / time.Duration(c.metrics.RequestsTotal)
	c.metrics.mu.Unlock()

	return resp, nil
}

// PostJSON sends a POST request with JSON body
func (c *HTTPClient) PostJSON(ctx context.Context, url string, data interface{}) (*http.Response, error) {
	jsonData, err := MarshalJSON(data)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal JSON: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(jsonData))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	return c.Do(ctx, req)
}

// Get sends a GET request
func (c *HTTPClient) Get(ctx context.Context, url string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Accept", "application/json")

	return c.Do(ctx, req)
}

// gzipCompress compresses data using gzip
func (c *HTTPClient) gzipCompress(data []byte) ([]byte, error) {
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	_, err := gz.Write(data)
	if err != nil {
		return nil, err
	}
	if err := gz.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// gzipDecompress decompresses gzip data
func (c *HTTPClient) gzipDecompress(data []byte) ([]byte, error) {
	reader, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	return io.ReadAll(reader)
}

// zstdCompress compresses data using zstd
func (c *HTTPClient) zstdCompress(data []byte) ([]byte, error) {
	return c.zstdEnc.EncodeAll(data, nil), nil
}

// zstdDecompress decompresses zstd data
func (c *HTTPClient) zstdDecompress(data []byte) ([]byte, error) {
	return c.zstdDec.DecodeAll(data, nil)
}

// calculateRetryDelay calculates exponential backoff with jitter
func (c *HTTPClient) calculateRetryDelay(attempt int) time.Duration {
	delay := c.config.InitialRetryDelay * time.Duration(1<<uint(attempt))
	if delay > c.config.MaxRetryDelay {
		delay = c.config.MaxRetryDelay
	}
	
	// Add jitter (±25%)
	jitter := time.Duration(float64(delay) * 0.25 * (float64(time.Now().UnixNano()%1000) / 1000.0 - 0.5))
	return delay + jitter
}

// GetMetrics returns current client metrics
func (c *HTTPClient) GetMetrics() *Metrics {
	c.metrics.mu.RLock()
	defer c.metrics.mu.RUnlock()
	
	return c.metrics
}

// Close closes the HTTP client and releases resources
func (c *HTTPClient) Close() {
	if c.zstdDec != nil {
		c.zstdDec.Close()
	}
	c.client.CloseIdleConnections()
	c.transport.CloseIdleConnections()
}
