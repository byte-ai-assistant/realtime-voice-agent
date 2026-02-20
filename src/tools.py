"""
Tools - Function calling implementations
Appointment booking, checking, and escalation handlers
"""

import os
import json
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)


class AppointmentManager:
    """Manages appointment booking and retrieval"""
    
    def __init__(self, db_path: str = "./data/appointments.json"):
        self.db_path = db_path
        self.appointments = self._load_appointments()
        logger.info(f"✅ AppointmentManager initialized with {len(self.appointments)} appointments")
    
    def _load_appointments(self) -> Dict:
        """Load appointments from JSON file"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    return json.load(f)
            else:
                return {}
        except Exception as e:
            logger.error(f"Error loading appointments: {e}")
            return {}
    
    def _save_appointments(self):
        """Save appointments to JSON file"""
        try:
            with open(self.db_path, 'w') as f:
                json.dump(self.appointments, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving appointments: {e}")
    
    async def book_appointment(
        self,
        date: str,
        time: str,
        name: str,
        phone: str
    ) -> Dict:
        """
        Book an appointment
        
        Args:
            date: Date in YYYY-MM-DD format
            time: Time in HH:MM format (24-hour)
            name: Customer name
            phone: Customer phone number
        
        Returns:
            Dict with success status and confirmation details
        """
        try:
            logger.info(f"📅 Booking appointment for {name} on {date} at {time}")
            
            # Validate date format
            try:
                appointment_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                return {
                    "success": False,
                    "error": "Formato de fecha inválido. Por favor usa AAAA-MM-DD"
                }
            
            # Validate time format
            try:
                appointment_time = datetime.strptime(time, "%H:%M")
            except ValueError:
                return {
                    "success": False,
                    "error": "Formato de hora inválido. Por favor usa HH:MM (formato 24 horas)"
                }
            
            # Check if date is in the future
            if appointment_date.date() < datetime.now().date():
                return {
                    "success": False,
                    "error": "No se pueden agendar citas en el pasado"
                }
            
            # Check business hours (9 AM - 5 PM)
            hour = appointment_time.hour
            if hour < 9 or hour >= 17:
                return {
                    "success": False,
                    "error": "Las citas solo están disponibles entre 9 AM y 5 PM"
                }
            
            # Generate appointment ID
            appointment_id = f"APT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Store appointment
            self.appointments[appointment_id] = {
                "id": appointment_id,
                "date": date,
                "time": time,
                "name": name,
                "phone": phone,
                "status": "confirmed",
                "booked_at": datetime.now().isoformat()
            }
            
            # Save to file
            self._save_appointments()
            
            logger.info(f"✅ Appointment booked: {appointment_id}")
            
            return {
                "success": True,
                "appointment_id": appointment_id,
                "date": date,
                "time": time,
                "name": name,
                "message": f"Cita confirmada para {name} el {date} a las {time}. Número de confirmación: {appointment_id}"
            }
            
        except Exception as e:
            logger.error(f"Error booking appointment: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to book appointment: {str(e)}"
            }
    
    async def check_appointment(self, phone: str) -> Dict:
        """
        Check appointment status by phone number
        
        Args:
            phone: Customer phone number
        
        Returns:
            Dict with appointment details or error
        """
        try:
            logger.info(f"🔍 Checking appointments for phone: {phone}")
            
            # Find appointments for this phone number
            found_appointments = []
            for apt_id, apt_data in self.appointments.items():
                if apt_data.get("phone") == phone:
                    found_appointments.append(apt_data)
            
            if not found_appointments:
                return {
                    "success": False,
                    "message": "No se encontraron citas para este número de teléfono"
                }
            
            # Return most recent appointment
            latest_apt = max(found_appointments, key=lambda x: x.get("booked_at", ""))
            
            return {
                "success": True,
                "appointment": {
                    "id": latest_apt["id"],
                    "date": latest_apt["date"],
                    "time": latest_apt["time"],
                    "name": latest_apt["name"],
                    "status": latest_apt["status"]
                },
                "message": f"Cita encontrada para {latest_apt['name']} el {latest_apt['date']} a las {latest_apt['time']}"
            }
            
        except Exception as e:
            logger.error(f"Error checking appointment: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to check appointment: {str(e)}"
            }


class EscalationHandler:
    """Handles escalation to human support"""
    
    def __init__(self):
        self.support_phone = os.getenv("SUPPORT_PHONE", "+1-555-SUPPORT")
        self.webhook_url = os.getenv("SUPPORT_WEBHOOK_URL")
        logger.info("✅ EscalationHandler initialized")
    
    async def escalate(
        self,
        reason: str,
        callback_number: Optional[str] = None
    ) -> Dict:
        """
        Escalate call to human support
        
        Args:
            reason: Reason for escalation
            callback_number: Optional callback number
        
        Returns:
            Dict with escalation status
        """
        try:
            logger.info(f"🆘 Escalating call: {reason}")
            
            # Create support ticket
            ticket_id = f"TICKET-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            ticket_data = {
                "ticket_id": ticket_id,
                "reason": reason,
                "callback_number": callback_number,
                "created_at": datetime.now().isoformat(),
                "status": "pending"
            }
            
            # Save ticket (in production, this would send to a real support system)
            tickets_path = "./data/support_tickets.json"
            os.makedirs(os.path.dirname(tickets_path), exist_ok=True)
            
            tickets = {}
            if os.path.exists(tickets_path):
                with open(tickets_path, 'r') as f:
                    tickets = json.load(f)
            
            tickets[ticket_id] = ticket_data
            
            with open(tickets_path, 'w') as f:
                json.dump(tickets, f, indent=2)
            
            logger.info(f"✅ Support ticket created: {ticket_id}")
            
            return {
                "success": True,
                "ticket_id": ticket_id,
                "support_phone": self.support_phone,
                "message": f"He creado un ticket de soporte ({ticket_id}) y nuestro equipo te devolverá la llamada pronto al {callback_number or 'número desde el que llamaste'}."
            }
            
        except Exception as e:
            logger.error(f"Error escalating: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to escalate: {str(e)}"
            }
