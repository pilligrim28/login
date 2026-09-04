package client

import (
	"bytes"
	"encoding/json"
)

// MarshalJSON marshals data to JSON with minimal whitespace
func MarshalJSON(data interface{}) ([]byte, error) {
	var buf bytes.Buffer
	encoder := json.NewEncoder(&buf)
	encoder.SetEscapeHTML(false)
	err := encoder.Encode(data)
	if err != nil {
		return nil, err
	}
	// Remove trailing newline
	result := buf.Bytes()
	if len(result) > 0 && result[len(result)-1] == '\n' {
		result = result[:len(result)-1]
	}
	return result, nil
}

// UnmarshalJSON unmarshals JSON data
func UnmarshalJSON(data []byte, v interface{}) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	return decoder.Decode(v)
}
