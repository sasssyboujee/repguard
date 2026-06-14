"""Mailer module for automating cold outreach emails via SMTP."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence

from repguard.utils import console
from dotenv import load_dotenv

load_dotenv()

# Example SMTP settings (would go in .env)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")


def send_outreach_email(
    to_email: str,
    subject: str,
    body: str,
    attachments: Sequence[Path] | None = None,
) -> bool:
    """Send an outreach email to a business with optional attachments.
    
    Args:
        to_email: Target business email address.
        subject: Email subject line.
        body: Plain text body of the email.
        attachments: List of file paths to attach (e.g., PDF reports).
        
    Returns:
        True if the email was sent successfully, False otherwise.
    """
    if not SMTP_USER or not SMTP_PASS:
        console.print("  [warning]⚠ Cannot send email: SMTP credentials not set in .env[/warning]")
        return False

    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg.set_content(body)

        if attachments:
            for filepath in attachments:
                if filepath.exists():
                    with open(filepath, 'rb') as f:
                        file_data = f.read()
                        file_name = filepath.name
                        # Simplistic MIME detection based on extension
                        maintype = 'application'
                        if file_name.endswith('.pdf'):
                            subtype = 'pdf'
                        elif file_name.endswith('.txt'):
                            maintype = 'text'
                            subtype = 'plain'
                        else:
                            subtype = 'octet-stream'
                            
                        msg.add_attachment(
                            file_data, 
                            maintype=maintype, 
                            subtype=subtype, 
                            filename=file_name
                        )

        # Connect and send
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
                
        console.print(f"  [success]✓ Email successfully sent to {to_email}[/success]")
        return True
        
    except Exception as e:
        console.print(f"  [danger]✗ Failed to send email to {to_email}: {e}[/danger]")
        return False
