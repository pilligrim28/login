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

	"massreg/internal/core/config"
	"massreg/internal/core/logger"
	"massreg/internal/services/proxy"
	"massreg/internal/services/registration"
	"massreg/internal/services/sms"
)

var (
	version   = "dev"
	buildTime = "unknown"
)

func main() {
	// Initialize configuration
	cfg, err := config.Load("configs/config.yaml")
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	// Initialize logger
	err = logger.Init(logger.Config{
		Level:      cfg.Logging.Level,
		Format:     cfg.Logging.Format,
		Output:     cfg.Logging.Output,
		FilePath:   cfg.Logging.FilePath,
		MaxSize:    cfg.Logging.MaxSize,
		MaxBackups: cfg.Logging.MaxBackups,
		MaxAge:     cfg.Logging.MaxAge,
		Compress:   cfg.Logging.Compress,
		ServiceName: "massreg",
	})
	if err != nil {
		log.Fatalf("Failed to init logger: %v", err)
	}
	zlog := logger.GetDefault().WithService("massreg")
	zlog.Info("Starting MassReg service", "version", version)

	// Initialize Redis cache
	rdb, err := initRedis(cfg)
	if err != nil {
		zlog.Fatal(err, "Failed to initialize Redis")
	}
	if rdb != nil {
		defer rdb.Close()
	}

	// Initialize SMS service
	smsService, err := sms.NewSMSClient(cfg.SMS, zlog)
	if err != nil {
		zlog.Fatal(err, "Failed to initialize SMS client")
	}

	// Initialize Proxy service
	proxyService, err := proxy.NewProxyManager(cfg.Proxy, zlog)
	if err != nil {
		zlog.Fatal(err, "Failed to initialize proxy manager")
	}
	if err := proxyService.StartHealthChecker(); err != nil {
		zlog.Warn("Proxy health checker failed to start", "error", err)
	}

	// Initialize Registration service
	regService, err := registration.NewRegistrationService(
		cfg.Services,
		proxyService,
		smsService,
		zlog,
	)
	if err != nil {
		zlog.Fatal(err, "Failed to initialize registration service")
	}

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

		api.POST("/workers/start", func(c *gin.Context) {
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
		zlog.Info("HTTP server started", "port", cfg.Server.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			zlog.Fatal(err, "HTTP server failed")
		}
	}()

	// Start worker pool if configured
	if cfg.Worker.PoolSize > 0 {
		zlog.Info("Starting worker pool", "pool_size", cfg.Worker.PoolSize)
		for i := 0; i < cfg.Worker.PoolSize; i++ {
			go func(workerID int) {
				zlog.Info("Worker started", "worker_id", workerID)
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

	zlog.Info("Shutting down server...")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		zlog.Fatal(err, "Server forced to shutdown")
	}

	proxyService.Stop()
	zlog.Info("MassReg service stopped")
}

func initRedis(cfg *config.Config) (*redis.Client, error) {
	if len(cfg.Redis.Addrs) == 0 {
		// Use in-memory cache if Redis is not configured
		log.Println("Redis not configured, using in-memory cache")
		return nil, nil
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.Redis.Addrs[0],
		Password: cfg.Redis.Password,
		PoolSize: cfg.Redis.PoolSize,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, err
	}

	return rdb, nil
}
