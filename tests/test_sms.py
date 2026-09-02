"""Тесты для модуля sms.py"""

import pytest
from unittest.mock import patch, MagicMock
from core.sms import SMSActivate


class TestSMSActivateInit:
    """Тесты инициализации SMSActivate."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        sms = SMSActivate(api_key="test_key")
        assert sms.api_key == "test_key"
        assert sms.service == "Microsoft"
        assert sms.country == "all"
        assert sms.max_price == 0
        assert sms.operator == ""
        assert sms.timeout == 20
        assert sms.base_url == "https://sms-activate.ru/stubs/handler_api.php"
        assert sms.verify_ssl is False

    def test_init_custom_values(self):
        """Тест инициализации с кастомными значениями."""
        sms = SMSActivate(
            api_key="custom_key",
            service="Google",
            country="RU",
            max_price=50.0,
            operator="MTS",
            timeout=30,
            base_url="https://custom.api.com/handler",
            verify_ssl=True
        )
        assert sms.api_key == "custom_key"
        assert sms.service == "Google"
        assert sms.country == "RU"
        assert sms.max_price == 50.0
        assert sms.operator == "MTS"
        assert sms.timeout == 30
        assert sms.base_url == "https://custom.api.com/handler"
        assert sms.verify_ssl is True


class TestSMSActivateServices:
    """Тесты для соответствия сервисов."""

    def test_service_mapping(self):
        """Тест маппинга сервисов."""
        sms = SMSActivate(api_key="test")
        
        assert sms._resolve_service("Microsoft") == "mm"
        assert sms._resolve_service("Outlook") == "mm"
        assert sms._resolve_service("Snapchat") == "sf"
        assert sms._resolve_service("Apple") == "at"
        assert sms._resolve_service("Google") == "go"
        assert sms._resolve_service("Telegram") == "tg"
        assert sms._resolve_service("UnknownService") == "UnknownService"


class TestSMSActivateRequest:
    """Тесты для метода _request."""

    @patch('httpx.Client')
    def test_request_success(self, mock_client):
        """Тест успешного запроса."""
        mock_response = MagicMock()
        mock_response.text = "ACCESS_BALANCE:100.5"
        mock_response.raise_for_status = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response
        mock_client.return_value.__enter__.return_value = mock_client_instance
        
        sms = SMSActivate(api_key="test_key")
        result = sms._request("getBalance")
        
        assert result == "ACCESS_BALANCE:100.5"
        mock_client_instance.get.assert_called_once()

    @patch('httpx.Client')
    def test_request_timeout(self, mock_client):
        """Тест таймаута запроса."""
        import httpx
        mock_client_instance = MagicMock()
        mock_client_instance.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client.return_value.__enter__.return_value = mock_client_instance
        
        sms = SMSActivate(api_key="test_key")
        result = sms._request("getBalance")
        
        assert result is None

    @patch('httpx.Client')
    def test_request_connect_error(self, mock_client):
        """Тест ошибки соединения."""
        import httpx
        mock_client_instance = MagicMock()
        mock_client_instance.get.side_effect = httpx.ConnectError("Connect error")
        mock_client.return_value.__enter__.return_value = mock_client_instance
        
        sms = SMSActivate(api_key="test_key")
        result = sms._request("getBalance")
        
        assert result is None


class TestSMSActivateBalance:
    """Тесты для метода get_balance."""

    @patch.object(SMSActivate, '_request')
    def test_get_balance_success(self, mock_request):
        """Тест успешного получения баланса."""
        mock_request.return_value = "ACCESS_BALANCE:100.5"
        
        sms = SMSActivate(api_key="test_key")
        balance = sms.get_balance()
        
        assert balance == 100.5

    @patch.object(SMSActivate, '_request')
    def test_get_balance_invalid_format(self, mock_request):
        """Тест неверного формата ответа."""
        mock_request.return_value = "INVALID_FORMAT"
        
        sms = SMSActivate(api_key="test_key")
        balance = sms.get_balance()
        
        assert balance is None

    @patch.object(SMSActivate, '_request')
    def test_get_balance_none_response(self, mock_request):
        """Тест отсутствия ответа."""
        mock_request.return_value = None
        
        sms = SMSActivate(api_key="test_key")
        balance = sms.get_balance()
        
        assert balance is None


class TestSMSActivateRentNumber:
    """Тесты для метода rent_number."""

    @patch.object(SMSActivate, '_request')
    @patch.object(SMSActivate, '_resolve_service')
    def test_rent_number_success(self, mock_resolve, mock_request):
        """Тест успешной аренды номера."""
        mock_resolve.return_value = "mm"
        mock_request.return_value = "ACCESS_NUMBER:12345:79991234567"
        
        sms = SMSActivate(api_key="test_key")
        result = sms.rent_number()
        
        assert result == {"id": "12345", "number": "79991234567"}

    @patch.object(SMSActivate, '_request')
    def test_rent_number_no_numbers(self, mock_request):
        """Тест отсутствия номеров."""
        mock_request.return_value = "NO_NUMBERS"
        
        sms = SMSActivate(api_key="test_key")
        result = sms.rent_number(max_retries=1)
        
        assert result is None

    @patch.object(SMSActivate, '_request')
    def test_rent_number_no_balance(self, mock_request):
        """Тест недостаточного баланса."""
        mock_request.return_value = "NO_BALANCE"
        
        sms = SMSActivate(api_key="test_key")
        result = sms.rent_number()
        
        assert result is None

    @patch.object(SMSActivate, '_request')
    def test_rent_number_bad_key(self, mock_request):
        """Тест неверного API-ключа."""
        mock_request.return_value = "BAD_KEY"
        
        sms = SMSActivate(api_key="test_key")
        result = sms.rent_number()
        
        assert result is None


class TestSMSActivateWaitCode:
    """Тесты для метода wait_code."""

    @patch('time.time')
    @patch('time.sleep')
    @patch.object(SMSActivate, '_request')
    def test_wait_code_success(self, mock_request, mock_sleep, mock_time):
        """Тест успешного получения кода."""
        mock_time.return_value = 0
        mock_request.return_value = "STATUS_OK:123456"
        
        sms = SMSActivate(api_key="test_key")
        code = sms.wait_code("12345", timeout=10, poll_interval=1)
        
        assert code == "123456"

    @patch('time.time')
    @patch('time.sleep')
    @patch.object(SMSActivate, '_request')
    def test_wait_code_timeout(self, mock_request, mock_sleep, mock_time):
        """Тест таймаута ожидания кода."""
        # Время всегда больше timeout
        mock_time.return_value = 100
        mock_request.return_value = "STATUS_WAIT_CODE"
        
        sms = SMSActivate(api_key="test_key")
        code = sms.wait_code("12345", timeout=10, poll_interval=1)
        
        assert code is None

    @patch.object(SMSActivate, '_request')
    def test_wait_code_cancelled(self, mock_request):
        """Тест отмены активации."""
        mock_request.return_value = "STATUS_CANCEL"
        
        sms = SMSActivate(api_key="test_key")
        code = sms.wait_code("12345")
        
        assert code is None


class TestSMSActivateConfirmCancel:
    """Тесты для методов confirm и cancel."""

    @patch.object(SMSActivate, '_request')
    def test_confirm_success(self, mock_request):
        """Тест успешного подтверждения."""
        mock_request.return_value = "ACCESS_ACTIVATION"
        
        sms = SMSActivate(api_key="test_key")
        sms.confirm("12345")
        
        mock_request.assert_called_once_with("setStatus", {"id": "12345", "status": 6})

    @patch.object(SMSActivate, '_request')
    def test_cancel_success(self, mock_request):
        """Тест успешной отмены."""
        mock_request.return_value = "ACCESS_CANCEL"
        
        sms = SMSActivate(api_key="test_key")
        sms.cancel("12345")
        
        mock_request.assert_called_once_with("setStatus", {"id": "12345", "status": 8})
