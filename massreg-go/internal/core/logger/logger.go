package logger

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"github.com/rs/zerolog"
	"gopkg.in/natefinch/lumberjack.v2"
)

// contextKey is a custom type for context keys to avoid collisions
type contextKey string

const (
	// CorrelationIDKey is the key used to store correlation ID in context
	CorrelationIDKey contextKey = "correlation_id"
	// ServiceNameKey is the key used to store service name in context
	ServiceNameKey contextKey = "service_name"
)

// Logger wraps zerolog.Logger with additional functionality
type Logger struct {
	zerolog.Logger
	serviceName string
	mu          sync.RWMutex
}

// Config holds logger configuration
type Config struct {
	Level      string
	Format     string
	Output     string
	FilePath   string
	MaxSize    int
	MaxBackups int
	MaxAge     int
	Compress   bool
	ServiceName string
}

// defaultLogger is the global logger instance
var (
	defaultLogger *Logger
	initOnce      sync.Once
)

// Init initializes the global logger with the given configuration
func Init(cfg Config) error {
	var err error
	initOnce.Do(func() {
		defaultLogger, err = New(cfg)
	})
	return err
}

// New creates a new logger with the given configuration
func New(cfg Config) (*Logger, error) {
	// Set log level
	level, err := zerolog.ParseLevel(cfg.Level)
	if err != nil {
		level = zerolog.InfoLevel
	}
	zerolog.SetGlobalLevel(level)

	// Create output writer
	var output io.Writer
	switch cfg.Output {
	case "stdout":
		output = os.Stdout
	case "stderr":
		output = os.Stderr
	case "file":
		output = &lumberjack.Logger{
			Filename:   cfg.FilePath,
			MaxSize:    cfg.MaxSize,
			MaxBackups: cfg.MaxBackups,
			MaxAge:     cfg.MaxAge,
			Compress:   cfg.Compress,
		}
	default:
		output = os.Stdout
	}

	// Set log format
	if cfg.Format == "json" {
		zerolog.TimeFieldFormat = time.RFC3339
	} else {
		zerolog.TimeFieldFormat = "2006-01-02 15:04:05"
		output = zerolog.ConsoleWriter{
			Out:        output,
			TimeFormat: "2006-01-02 15:04:05",
		}
	}

	// Create logger
	logger := zerolog.New(output).
		With().
		Timestamp().
		Caller().
		Logger()

	l := &Logger{
		Logger:      logger,
		serviceName: cfg.ServiceName,
	}

	return l, nil
}

// GetDefault returns the default logger instance
func GetDefault() *Logger {
	if defaultLogger == nil {
		// Initialize with defaults if not already initialized
		cfg := Config{
			Level:       "info",
			Format:      "json",
			Output:      "stdout",
			ServiceName: "massreg",
		}
		defaultLogger, _ = New(cfg)
	}
	return defaultLogger
}

// WithService creates a new logger with the specified service name
func (l *Logger) WithService(serviceName string) *Logger {
	return &Logger{
		Logger:      l.Logger.With().Str("service", serviceName).Logger(),
		serviceName: serviceName,
	}
}

// WithCorrelationID adds a correlation ID to the logger
func (l *Logger) WithCorrelationID(correlationID string) *Logger {
	return &Logger{
		Logger: l.Logger.With().Str("correlation_id", correlationID).Logger(),
	}
}

// WithContext adds context values to the logger
func (l *Logger) WithContext(ctx context.Context) *Logger {
	logger := l
	if correlationID := GetCorrelationID(ctx); correlationID != "" {
		logger = logger.WithCorrelationID(correlationID)
	}
	if serviceName := GetServiceName(ctx); serviceName != "" {
		logger = logger.WithService(serviceName)
	}
	return logger
}

// Debug logs a debug message
func (l *Logger) Debug(msg string, fields ...interface{}) {
	event := l.Logger.Debug()
	for i := 0; i < len(fields); i += 2 {
		if i+1 < len(fields) {
			event = event.Interface(fmt.Sprint(fields[i]), fields[i+1])
		}
	}
	event.Msg(msg)
}

// Info logs an info message
func (l *Logger) Info(msg string, fields ...interface{}) {
	event := l.Logger.Info()
	for i := 0; i < len(fields); i += 2 {
		if i+1 < len(fields) {
			event = event.Interface(fmt.Sprint(fields[i]), fields[i+1])
		}
	}
	event.Msg(msg)
}

// Warn logs a warning message
func (l *Logger) Warn(msg string, fields ...interface{}) {
	event := l.Logger.Warn()
	for i := 0; i < len(fields); i += 2 {
		if i+1 < len(fields) {
			event = event.Interface(fmt.Sprint(fields[i]), fields[i+1])
		}
	}
	event.Msg(msg)
}

// Error logs an error message
func (l *Logger) Error(err error, msg string, fields ...interface{}) {
	event := l.Logger.Error().Err(err)
	for i := 0; i < len(fields); i += 2 {
		if i+1 < len(fields) {
			event = event.Interface(fmt.Sprint(fields[i]), fields[i+1])
		}
	}
	event.Msg(msg)
}

// Fatal logs a fatal message and exits
func (l *Logger) Fatal(err error, msg string, fields ...interface{}) {
	event := l.Logger.Fatal().Err(err)
	for i := 0; i < len(fields); i += 2 {
		if i+1 < len(fields) {
			event = event.Interface(fmt.Sprint(fields[i]), fields[i+1])
		}
	}
	event.Msg(msg)
}

// WithFields returns a new logger with the given fields
func (l *Logger) WithFields(fields map[string]interface{}) *Logger {
	logger := l.Logger
	for k, v := range fields {
		logger = logger.With().Interface(k, v).Logger()
	}
	return &Logger{
		Logger:      logger,
		serviceName: l.serviceName,
	}
}

// WithField returns a new logger with the given field
func (l *Logger) WithField(key string, value interface{}) *Logger {
	return &Logger{
		Logger:      l.Logger.With().Interface(key, value).Logger(),
		serviceName: l.serviceName,
	}
}

// WithError returns a new logger with the given error
func (l *Logger) WithError(err error) *Logger {
	return &Logger{
		Logger:      l.Logger.With().Err(err).Logger(),
		serviceName: l.serviceName,
	}
}

// WithCallerSkip skips the specified number of caller frames
func (l *Logger) WithCallerSkip(skip int) *Logger {
	// Note: CallerWithSkip is available in newer zerolog versions
	// For Go 1.19 compatibility, we just return the logger as-is
	_ = skip
	return &Logger{
		Logger:      l.Logger,
		serviceName: l.serviceName,
	}
}

// GetCallerInfo returns the caller function and file information
func GetCallerInfo(skip int) (function string, file string, line int) {
	pc, file, line, ok := runtime.Caller(skip + 1)
	if !ok {
		return "unknown", "unknown", 0
	}

	function = runtime.FuncForPC(pc).Name()
	file = filepath.Base(file)

	return function, file, line
}

// WithCorrelationIDToContext adds correlation ID to context
func WithCorrelationIDToContext(ctx context.Context, correlationID string) context.Context {
	return context.WithValue(ctx, CorrelationIDKey, correlationID)
}

// WithServiceNameToContext adds service name to context
func WithServiceNameToContext(ctx context.Context, serviceName string) context.Context {
	return context.WithValue(ctx, ServiceNameKey, serviceName)
}

// GetCorrelationID retrieves correlation ID from context
func GetCorrelationID(ctx context.Context) string {
	if v := ctx.Value(CorrelationIDKey); v != nil {
		if id, ok := v.(string); ok {
			return id
		}
	}
	return ""
}

// GetServiceName retrieves service name from context
func GetServiceName(ctx context.Context) string {
	if v := ctx.Value(ServiceNameKey); v != nil {
		if name, ok := v.(string); ok {
			return name
		}
	}
	return ""
}

// GenerateCorrelationID generates a new correlation ID
func GenerateCorrelationID() string {
	return fmt.Sprintf("%d", time.Now().UnixNano())
}

// With returns a context with correlation ID and service name
func With(ctx context.Context, correlationID, serviceName string) context.Context {
	ctx = WithCorrelationIDToContext(ctx, correlationID)
	ctx = WithServiceNameToContext(ctx, serviceName)
	return ctx
}

// Debug logs a debug message using the default logger
func Debug(msg string, fields ...interface{}) {
	GetDefault().Debug(msg, fields...)
}

// Info logs an info message using the default logger
func Info(msg string, fields ...interface{}) {
	GetDefault().Info(msg, fields...)
}

// Warn logs a warning message using the default logger
func Warn(msg string, fields ...interface{}) {
	GetDefault().Warn(msg, fields...)
}

// Error logs an error message using the default logger
func Error(err error, msg string, fields ...interface{}) {
	GetDefault().Error(err, msg, fields...)
}

// Fatal logs a fatal message using the default logger
func Fatal(err error, msg string, fields ...interface{}) {
	GetDefault().Fatal(err, msg, fields...)
}
