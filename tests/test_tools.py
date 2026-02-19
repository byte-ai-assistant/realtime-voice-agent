"""
Unit tests for Tools (appointment booking, escalation)
"""

import pytest
import asyncio
import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from tools import AppointmentManager, EscalationHandler


@pytest.fixture
def appointment_manager(tmp_path):
    """Create AppointmentManager with temp database"""
    db_path = tmp_path / "test_appointments.json"
    return AppointmentManager(db_path=str(db_path))


@pytest.mark.asyncio
async def test_book_appointment_success(appointment_manager):
    """Test successful appointment booking"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    result = await appointment_manager.book_appointment(
        date=tomorrow,
        time="14:00",
        name="John Doe",
        phone="+1234567890"
    )

    assert result["success"] is True
    assert "appointment_id" in result
    assert result["name"] == "John Doe"


@pytest.mark.asyncio
async def test_book_appointment_past_date(appointment_manager):
    """Test booking appointment in the past fails"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    result = await appointment_manager.book_appointment(
        date=yesterday,
        time="14:00",
        name="John Doe",
        phone="+1234567890"
    )

    assert result["success"] is False
    assert "past" in result["error"].lower()


@pytest.mark.asyncio
async def test_book_appointment_invalid_time(appointment_manager):
    """Test booking outside business hours fails"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    result = await appointment_manager.book_appointment(
        date=tomorrow,
        time="20:00",  # 8 PM - outside business hours
        name="John Doe",
        phone="+1234567890"
    )

    assert result["success"] is False
    assert "9 am" in result["error"].lower() or "business hours" in result["error"].lower()


@pytest.mark.asyncio
async def test_book_appointment_invalid_date_format(appointment_manager):
    """Test booking with invalid date format fails"""
    result = await appointment_manager.book_appointment(
        date="not-a-date",
        time="14:00",
        name="John Doe",
        phone="+1234567890"
    )

    assert result["success"] is False
    assert "invalid date" in result["error"].lower()


@pytest.mark.asyncio
async def test_book_appointment_invalid_time_format(appointment_manager):
    """Test booking with invalid time format fails"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    result = await appointment_manager.book_appointment(
        date=tomorrow,
        time="not-a-time",
        name="John Doe",
        phone="+1234567890"
    )

    assert result["success"] is False
    assert "invalid time" in result["error"].lower()


@pytest.mark.asyncio
async def test_check_appointment(appointment_manager):
    """Test checking appointment by phone"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    phone = "+1234567890"

    # Book appointment first
    await appointment_manager.book_appointment(
        date=tomorrow,
        time="14:00",
        name="John Doe",
        phone=phone
    )

    # Check appointment
    result = await appointment_manager.check_appointment(phone=phone)

    assert result["success"] is True
    assert "appointment" in result
    assert result["appointment"]["name"] == "John Doe"


@pytest.mark.asyncio
async def test_check_nonexistent_appointment(appointment_manager):
    """Test checking appointment that doesn't exist"""
    result = await appointment_manager.check_appointment(phone="+9999999999")

    assert result["success"] is False
    assert "no appointments found" in result["message"].lower() or "not found" in result["message"].lower()


@pytest.mark.asyncio
async def test_escalation(tmp_path):
    """Test escalation handler"""
    # Use tmp_path for ticket storage
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)

    try:
        handler = EscalationHandler()

        result = await handler.escalate(
            reason="Complex technical issue",
            callback_number="+1234567890"
        )

        assert result["success"] is True
        assert "ticket_id" in result
        assert result["support_phone"] is not None
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_escalation_without_callback(tmp_path):
    """Test escalation without callback number"""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)

    try:
        handler = EscalationHandler()

        result = await handler.escalate(
            reason="Need human help"
        )

        assert result["success"] is True
        assert "ticket_id" in result
    finally:
        os.chdir(original_cwd)
