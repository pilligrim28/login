package cache

import (
	"context"
	"time"

	"github.com/go-redis/redis/v8"
)

// Cache is an in-memory/Redis cache abstraction
type Cache struct {
	rdb     *redis.Client
	timeout time.Duration
}

// NewCache creates a new cache instance
func NewCache(rdb *redis.Client, timeout time.Duration) *Cache {
	return &Cache{
		rdb:     rdb,
		timeout: timeout,
	}
}

// Get retrieves a value from cache
func (c *Cache) Get(ctx context.Context, key string) (string, error) {
	if c.rdb == nil {
		return "", nil
	}
	return c.rdb.Get(ctx, key).Result()
}

// Set stores a value in cache
func (c *Cache) Set(ctx context.Context, key string, value string, ttl time.Duration) error {
	if c.rdb == nil {
		return nil
	}
	if ttl == 0 {
		ttl = c.timeout
	}
	return c.rdb.Set(ctx, key, value, ttl).Err()
}

// Delete removes a value from cache
func (c *Cache) Delete(ctx context.Context, key string) error {
	if c.rdb == nil {
		return nil
	}
	return c.rdb.Del(ctx, key).Err()
}

// Exists checks if a key exists in cache
func (c *Cache) Exists(ctx context.Context, key string) (bool, error) {
	if c.rdb == nil {
		return false, nil
	}
	result, err := c.rdb.Exists(ctx, key).Result()
	return result > 0, err
}

// Close closes the cache connection
func (c *Cache) Close() error {
	if c.rdb == nil {
		return nil
	}
	return c.rdb.Close()
}
