package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-redis/redis/v8"
	"github.com/lib/pq"
	"github.com/rs/zerolog"
	"github.com/spf13/viper"

	"massreg-go/internal/core/config"
	"massreg-go/internal/core/logger"
	"massreg-go/internal/services/proxy"
	"massreg-go/internal/services/registration"
	"massreg-go/internal/services/sms"
	"massreg-go/internal/repository"
	"massreg-go/internal/cache"
	"massreg-go/internal/ml"
)

var (
	version   = "dev"
	buildTime = "unknown"
)

func main() {
	// Initialize configuration
	cfg, err := config.LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	// Initialize logger
	logLevel := zerolog.InfoLevel
	if cfg.Logging.Level == "debug" {
		logLevel = zerolog.DebugLevel
	} else if cfg.Logging.Level == "warn" {
		logLevel = zerolog.WarnLevel
	} else if cfg.Logging.Level == "error" {
		logLevel = zerolog.ErrorLevel
	}

	logger.InitLogger(logLevel, cfg.Logging.Format)
	zlog := logger.GetLogger().With().Str("service", "massreg").Str("version", version).Logger()
	zlog.Info().Msg("Starting MassReg service")

	// Initialize database
	db, err := initDatabase(cfg)
	if err != nil {
		zlog.Fatal().Err(err).Msg("Failed to initialize database")
	}
	defer db.Close()

	// Initialize Redis cache
	rdb, err := initRedis(cfg)
	if err != nil {
		zlog.Fatal().Err(err).Msg("Failed to initialize Redis")
	}
	defer rdb.Close()

	// Initialize SMS service
	smsService := sms.NewService(&cfg.SMS, rdb)

	// Initialize Proxy service
	proxyService := proxy.NewPoolManager(&cfg.Proxy, rdb)
	if err := proxyService.StartHealthChecker(); err != nil {
		zlog.Warn().Err(err).Msg("Proxy health checker failed to start")
	}

	// Initialize ML service
	var mlService *ml.Service
	if cfg.ML.Enabled {
		mlService = ml.NewService(&cfg.ML, rdb)
		if err := mlService.LoadModel(); err != nil {
			zlog.Warn().Err(err).Msg("Failed to load ML model, starting without it")
		}
	}

	// Initialize Registration service
	regService := registration.NewService(
		&cfg.Worker,
		smsService,
		proxyService,
		mlService,
		db,
		rdb,
	)

	// Setup Gin router
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(logger.LoggerMiddleware())

	// Health check endpoint
	router.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":    "healthy",
			"service":   "massreg",
			"version":   version,
			"timestamp": time.Now().UTC(),
		})
	})

	// API endpoints
	api := router.Group("/api/v1")
	{
		api.POST("/register", func(c *gin.Context) {
			var req registration.RegistrationRequest
			if err := c.ShouldBindJSON(&req); err != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
				return
			}

			result, err := regService.Register(c.Request.Context(), &req)
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}

			c.JSON(http.StatusOK, result)
		})

		api.GET("/stats", func(c *gin.Context) {
			stats := regService.GetStats()
			c.JSON(http.StatusOK, stats)
		})

		api.GET("/proxies", func(c *gin.Context) {
			proxies := proxyService.GetHealthyProxies()
			c.JSON(http.StatusOK, gin.H{"count": len(proxies), "proxies": proxies})
		})

		api.POST "/workers/start", func(c *gin.Context) {
			var req struct {
				Total int `json:"total"`
			}
			if err := c.ShouldBindJSON(&req); err != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
				return
			}

			go func() {
				ctx := context.Background()
				for i := 0; i < req.Total; i++ {
					select {
					case <-ctx.Done():
						return
					default:
						regService.ProcessNextTask(ctx)
					}
				}
			}()

			c.JSON(http.StatusOK, gin.H{"message": fmt.Sprintf("Started processing %d registrations", req.Total)})
		})
	}

	// Create HTTP server
	srv := &http.Server{
		Addr:         fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port),
		Handler:      router,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Start server in goroutine
	go func() {
		zlog.Info().Int("port", cfg.Server.Port).Msg("HTTP server started")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			zlog.Fatal().Err(err).Msg("HTTP server failed")
		}
	}()

	// Start worker pool if configured
	if cfg.Worker.Threads > 0 {
		zlog.Info().Int("threads", cfg.Worker.Threads).Msg("Starting worker pool")
		for i := 0; i < cfg.Worker.Threads; i++ {
			go func(workerID int) {
				zlog.Info().Int("worker_id", workerID).Msg("Worker started")
				for {
					select {
					case <-time.After(1 * time.Second):
						// Process tasks periodically
						regService.ProcessNextTask(context.Background())
					}
				}
			}(i)
		}
	}

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	zlog.Info().Msg("Shutting down server...")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		zlog.Fatal().Err(err).Msg("Server forced to shutdown")
	}

	proxyService.Stop()
	zlog.Info().Msg("MassReg service stopped")
}

func initDatabase(cfg *config.Config) (*repository.Database, error) {
	switch cfg.Database.Type {
	case "postgres":
		return repository.NewPostgresDB(cfg.Database.PostgresURL)
	case "sqlite":
		return repository.NewSQLiteDB(cfg.Database.SQLitePath)
	default:
		return nil, fmt.Errorf("unsupported database type: %s", cfg.Database.Type)
	}
}

func initRedis(cfg *config.Config) (*redis.Client, error) {
	if len(cfg.Redis.Addrs) == 0 {
		// Use in-memory cache if Redis is not configured
		log.Println("Redis not configured, using in-memory cache")
		return nil, nil
	}

	rdb := redis.NewClusterClient(&redis.ClusterOptions{
		Addrs:     cfg.Redis.Addrs,
		Password:  cfg.Redis.Password,
		PoolSize:  cfg.Redis.PoolSize,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, err
	}

	return rdb, nil
}
