package config

import (
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/spf13/viper"
)

// Config holds all configuration for the application
type Config struct {
	Server   ServerConfig   `mapstructure:"server"`
	Database DatabaseConfig `mapstructure:"database"`
	Redis    RedisConfig    `mapstructure:"redis"`
	Kafka    KafkaConfig    `mapstructure:"kafka"`
	SMS      SMSConfig      `mapstructure:"sms"`
	Proxy    ProxyConfig    `mapstructure:"proxy"`
	Worker   WorkerConfig   `mapstructure:"worker"`
	ML       MLConfig       `mapstructure:"ml"`
	Cache    CacheConfig    `mapstructure:"cache"`
	Logging  LoggingConfig  `mapstructure:"logging"`
	Metrics  MetricsConfig  `mapstructure:"metrics"`
	Security SecurityConfig `mapstructure:"security"`
	Services ServicesConfig `mapstructure:"services"`
}

// ServerConfig holds server configuration
type ServerConfig struct {
	Host            string        `mapstructure:"host"`
	Port            int           `mapstructure:"port"`
	JWTSecret       string        `mapstructure:"jwt_secret"`
	APIKey          string        `mapstructure:"api_key"`
	ReadTimeout     time.Duration `mapstructure:"read_timeout"`
	WriteTimeout    time.Duration `mapstructure:"write_timeout"`
	ShutdownTimeout time.Duration `mapstructure:"shutdown_timeout"`
}

// DatabaseConfig holds database configuration
type DatabaseConfig struct {
	Driver          string        `mapstructure:"driver"`
	DSN             string        `mapstructure:"dsn"`
	MaxOpenConns    int           `mapstructure:"max_open_conns"`
	MaxIdleConns    int           `mapstructure:"max_idle_conns"`
	ConnMaxLifetime time.Duration `mapstructure:"conn_max_lifetime"`
}

// RedisConfig holds Redis configuration
type RedisConfig struct {
	Addrs            []string      `mapstructure:"addrs"`
	Password         string        `mapstructure:"password"`
	PoolSize         int           `mapstructure:"pool_size"`
	MinIdleConns     int           `mapstructure:"min_idle_conns"`
	ConnMaxIdleTime  time.Duration `mapstructure:"conn_max_idle_time"`
	DB               int           `mapstructure:"db"`
}

// KafkaConfig holds Kafka configuration
type KafkaConfig struct {
	Brokers         []string `mapstructure:"brokers"`
	Topic           string   `mapstructure:"topic"`
	Partitions      int      `mapstructure:"partitions"`
	ConsumerGroup   string   `mapstructure:"consumer_group"`
	ReaderMinBytes  int      `mapstructure:"reader_min_bytes"`
	ReaderMaxBytes  int      `mapstructure:"reader_max_bytes"`
	WriterMaxAttempts int    `mapstructure:"writer_max_attempts"`
}

// SMSProviderConfig holds SMS provider configuration
type SMSProviderConfig struct {
	Name          string `mapstructure:"name"`
	APIKey        string `mapstructure:"api_key"`
	APIURL        string `mapstructure:"api_url"`
	Weight        int    `mapstructure:"weight"`
	MaxConcurrent int    `mapstructure:"max_concurrent"`
}

// SMSConfig holds SMS configuration
type SMSConfig struct {
	Providers   []SMSProviderConfig `mapstructure:"providers"`
	Services    []string            `mapstructure:"services"`
	RateLimit   int                 `mapstructure:"rate_limit"`
	Timeout     time.Duration       `mapstructure:"timeout"`
	CacheTTL    time.Duration       `mapstructure:"cache_ttl"`
}

// ProxyHealthCheckConfig holds proxy health check configuration
type ProxyHealthCheckConfig struct {
	Enabled          bool          `mapstructure:"enabled"`
	Interval         time.Duration `mapstructure:"interval"`
	Timeout          time.Duration `mapstructure:"timeout"`
	DeadThreshold    int           `mapstructure:"dead_threshold"`
	RecoveryInterval time.Duration `mapstructure:"recovery_interval"`
}

// ProxyConfig holds proxy configuration
type ProxyConfig struct {
	Enabled       bool                    `mapstructure:"enabled"`
	Type          string                  `mapstructure:"type"`
	Strategy      string                  `mapstructure:"strategy"`
	Proxies       []string                `mapstructure:"proxies"`
	RotationURL   string                  `mapstructure:"rotation_url"`
	HealthCheck   ProxyHealthCheckConfig  `mapstructure:"health_check"`
}

// WorkerConfig holds worker configuration
type WorkerConfig struct {
	PoolSize                int           `mapstructure:"pool_size"`
	QueueSize               int           `mapstructure:"queue_size"`
	BatchSize               int           `mapstructure:"batch_size"`
	MaxRetries              int           `mapstructure:"max_retries"`
	NumberRetries           int           `mapstructure:"number_retries"`
	RegistrationTimeout     time.Duration `mapstructure:"registration_timeout"`
	GracefulShutdownTimeout time.Duration `mapstructure:"graceful_shutdown_timeout"`
}

// MLConfig holds ML configuration
type MLConfig struct {
	Enabled          bool          `mapstructure:"enabled"`
	ModelPath        string        `mapstructure:"model_path"`
	LearningRate     float64       `mapstructure:"learning_rate"`
	L2Regularization float64       `mapstructure:"l2_regularization"`
	MinSamples       int           `mapstructure:"min_samples"`
	UpdateInterval   time.Duration `mapstructure:"update_interval"`
	RedisKey         string        `mapstructure:"redis_key"`
}

// CacheConfig holds cache configuration
type CacheConfig struct {
	DefaultTTL     time.Duration `mapstructure:"default_ttl"`
	EmailTTL       time.Duration `mapstructure:"email_ttl"`
	PhoneTTL       time.Duration `mapstructure:"phone_ttl"`
	ProxyTTL       time.Duration `mapstructure:"proxy_ttl"`
	SMSStatusTTL   time.Duration `mapstructure:"sms_status_ttl"`
}

// LoggingConfig holds logging configuration
type LoggingConfig struct {
	Level      string `mapstructure:"level"`
	Format     string `mapstructure:"format"`
	Output     string `mapstructure:"output"`
	FilePath   string `mapstructure:"file_path"`
	MaxSize    int    `mapstructure:"max_size"`
	MaxBackups int    `mapstructure:"max_backups"`
	MaxAge     int    `mapstructure:"max_age"`
	Compress   bool   `mapstructure:"compress"`
}

// MetricsConfig holds metrics configuration
type MetricsConfig struct {
	Enabled bool   `mapstructure:"enabled"`
	Port    int    `mapstructure:"port"`
	Path    string `mapstructure:"path"`
}

// SecurityConfig holds security configuration
type SecurityConfig struct {
	AESKey             string        `mapstructure:"aes_key"`
	JWTExpiry          time.Duration `mapstructure:"jwt_expiry"`
	JWTRefreshExpiry   time.Duration `mapstructure:"jwt_refresh_expiry"`
	RateLimitRequests  int           `mapstructure:"rate_limit_requests"`
	RateLimitWindow    time.Duration `mapstructure:"rate_limit_window"`
}

// ServiceEndpointConfig holds service endpoint configuration
type ServiceEndpointConfig struct {
	Enabled bool          `mapstructure:"enabled"`
	APIURL  string        `mapstructure:"api_url"`
	Timeout time.Duration `mapstructure:"timeout"`
}

// ServicesConfig holds all service configurations
type ServicesConfig struct {
	Microsoft  ServiceEndpointConfig `mapstructure:"microsoft"`
	Google     ServiceEndpointConfig `mapstructure:"google"`
	Apple      ServiceEndpointConfig `mapstructure:"apple"`
	Snapchat   ServiceEndpointConfig `mapstructure:"snapchat"`
	Instagram  ServiceEndpointConfig `mapstructure:"instagram"`
	Facebook   ServiceEndpointConfig `mapstructure:"facebook"`
	Discord    ServiceEndpointConfig `mapstructure:"discord"`
}

// Load reads configuration from file and environment variables
func Load(configPath string) (*Config, error) {
	v := viper.New()

	// Set defaults
	setDefaults(v)

	// Read config file
	if configPath != "" {
		v.SetConfigFile(configPath)
		v.SetConfigType("yaml")
		
		if err := v.ReadInConfig(); err != nil {
			return nil, fmt.Errorf("failed to read config file: %w", err)
		}
	}

	// Bind environment variables
	bindEnv(v)

	// Unmarshal into Config struct
	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	// Validate configuration
	if err := validate(&cfg); err != nil {
		return nil, fmt.Errorf("config validation failed: %w", err)
	}

	return &cfg, nil
}

// setDefaults sets default values for configuration
func setDefaults(v *viper.Viper) {
	v.SetDefault("server.host", "0.0.0.0")
	v.SetDefault("server.port", 8000)
	v.SetDefault("server.read_timeout", "30s")
	v.SetDefault("server.write_timeout", "30s")
	v.SetDefault("server.shutdown_timeout", "10s")

	v.SetDefault("database.driver", "postgres")
	v.SetDefault("database.max_open_conns", 50)
	v.SetDefault("database.max_idle_conns", 10)
	v.SetDefault("database.conn_max_lifetime", "5m")

	v.SetDefault("redis.pool_size", 100)
	v.SetDefault("redis.min_idle_conns", 10)
	v.SetDefault("redis.db", 0)

	v.SetDefault("kafka.partitions", 50)
	v.SetDefault("kafka.consumer_group", "workers")

	v.SetDefault("worker.pool_size", 100)
	v.SetDefault("worker.queue_size", 10000)
	v.SetDefault("worker.batch_size", 50)
	v.SetDefault("worker.max_retries", 3)

	v.SetDefault("logging.level", "info")
	v.SetDefault("logging.format", "json")
	v.SetDefault("logging.output", "stdout")

	v.SetDefault("metrics.enabled", true)
	v.SetDefault("metrics.port", 9090)
	v.SetDefault("metrics.path", "/metrics")

	v.SetDefault("cache.default_ttl", "300s")
	v.SetDefault("cache.email_ttl", "86400s")
	v.SetDefault("cache.phone_ttl", "3600s")
}

// bindEnv binds environment variables to config keys
func bindEnv(v *viper.Viper) {
	v.BindEnv("server.jwt_secret", "JWT_SECRET")
	v.BindEnv("server.api_key", "API_KEY")
	v.BindEnv("database.dsn", "POSTGRES_URL")
	v.BindEnv("redis.addrs", "REDIS_NODES")
	v.BindEnv("redis.password", "REDIS_PASSWORD")
	v.BindEnv("kafka.brokers", "KAFKA_BROKERS")
	v.BindEnv("sms.providers[0].api_key", "SMS_API_KEY_1")
	v.BindEnv("proxy.proxies", "PROXY_LIST")
	v.BindEnv("proxy.rotation_url", "PROXY_ROTATION_URL")
	v.BindEnv("security.aes_key", "AES_ENCRYPTION_KEY")
}

// validate validates the configuration
func validate(cfg *Config) error {
	if cfg.Server.Port < 1 || cfg.Server.Port > 65535 {
		return fmt.Errorf("invalid server port: %d", cfg.Server.Port)
	}

	if cfg.Worker.PoolSize < 1 {
		return fmt.Errorf("worker pool size must be at least 1")
	}

	if cfg.Worker.BatchSize < 1 {
		return fmt.Errorf("worker batch size must be at least 1")
	}

	return nil
}

// GetEnv retrieves environment variable with fallback
func GetEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// ParseDurationList parses a comma-separated list of durations
func ParseDurationList(s string) []time.Duration {
	if s == "" {
		return nil
	}

	parts := strings.Split(s, ",")
	durations := make([]time.Duration, 0, len(parts))

	for _, part := range parts {
		if d, err := time.ParseDuration(strings.TrimSpace(part)); err == nil {
			durations = append(durations, d)
		}
	}

	return durations
}

// ParseStringList parses a comma-separated list of strings
func ParseStringList(s string) []string {
	if s == "" {
		return nil
	}

	parts := strings.Split(s, ",")
	result := make([]string, 0, len(parts))

	for _, part := range parts {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			result = append(result, trimmed)
		}
	}

	return result
}
