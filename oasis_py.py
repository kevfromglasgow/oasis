import streamlit as st
import pandas as pd
import json
import os
import threading
import time
from datetime import datetime
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import hashlib
import re

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# File paths
USERS_FILE = 'subscribers.json'
STATUS_FILE = 'monitor_status.json'

@st.cache_resource
def get_driver():
    """Sets up and returns a cached Selenium Chrome driver for UI actions."""
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
    return webdriver.Chrome(service=service, options=options)


class TwicketsMonitor:
    def __init__(self, url, sender_email, sender_password, admin_email=None, first_dibs_delay=90, smtp_server="smtp.gmail.com", smtp_port=587):
        self.url = url
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.admin_email = admin_email
        self.first_dibs_delay = first_dibs_delay
        self.known_tickets = set()
        self.is_running = False
        self.subscribers = self.load_subscribers()

    def load_subscribers(self):
        try:
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'r') as f: return json.load(f)
            return []
        except Exception as e:
            logging.error(f"Error loading subscribers: {e}"); return []

    def save_subscribers(self):
        try:
            with open(USERS_FILE, 'w') as f: json.dump(self.subscribers, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving subscribers: {e}")
    
    # --- METHOD RESTORED ---
    def get_status(self):
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, 'r') as f:
                    return json.load(f)
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}
        except Exception as e:
            logging.error(f"Error getting status: {e}")
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}

    # --- METHOD RESTORED ---
    def get_subscriber_count(self):
        return len(self.subscribers)

    def add_subscriber(self, email, name=""):
        email = email.lower().strip()
        if any(s['email'] == email for s in self.subscribers):
            return False, "Email already subscribed"
        self.subscribers.append({'email': email, 'name': name, 'subscribed_at': datetime.now().isoformat()})
        self.save_subscribers()
        self.notify_new_subscriber_of_current_tickets(email, name)
        return True, "Successfully subscribed!"

    def notify_new_subscriber_of_current_tickets(self, email, name):
        try:
            driver = get_driver()
            current_tickets = self.check_tickets(driver=driver, is_one_off_check=True)
            if current_tickets:
                self.send_welcome_email_with_current_tickets(email, name, current_tickets)
            else:
                self.send_welcome_confirmation_email(email, name)
        except Exception as e:
            logging.error(f"Error during one-off check for new subscriber: {e}")

    def send_email(self, recipient, subject, body):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, recipient, msg.as_string())
            server.quit()
            logging.info(f"Email sent successfully to {recipient}")
        except Exception as e:
            logging.error(f"Failed to send email to {recipient}: {e}")

    def send_welcome_email_with_current_tickets(self, email, name, tickets):
        subject = f"🎸 Welcome! {len(tickets)} Oasis Tickets Currently Available!"
        tickets_info = "\n".join([f"\nTicket {i+1}:\n  Price: {t.get('price', 'N/A')}\n  Details: {t.get('text', '')[:150]}...\n" for i, t in enumerate(tickets)])
        display_name = name or 'Oasis Fan'
        body = f"Hi {display_name}!\n\n🎸 WELCOME! 🎸\n\nGreat news! There are currently {len(tickets)} tickets available RIGHT NOW!\n\nEvent URL: {self.url}\n\n{tickets_info}\nCheck the page immediately!\n\nYou'll get instant alerts for NEW tickets.\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.send_email(email, subject, body)

    def send_welcome_confirmation_email(self, email, name):
        subject = "✅ You're Subscribed to Oasis Ticket Alerts!"
        display_name = name or 'Oasis Fan'
        body = f"Hi {display_name}!\n\n🎸 WELCOME! 🎸\n\nYou're all set! There are no tickets available right now, but we'll email you the moment new ones are listed.\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.send_email(email, subject, body)

    def remove_subscriber(self, email):
        email = email.lower().strip()
        original_count = len(self.subscribers)
        self.subscribers = [s for s in self.subscribers if s['email'] != email]
        self.save_subscribers()
        return len(self.subscribers) < original_count

    def update_status(self, status_data):
        try:
            with open(STATUS_FILE, 'w') as f: json.dump(status_data, f, indent=2)
        except Exception as e:
            logging.error(f"Error updating status: {e}")

    def check_tickets(self, driver, is_one_off_check=False):
        try:
            driver.get(self.url)
            time.sleep(3)
            try:
                if 'display: none' not in driver.find_element(By.ID, 'no-listings-found').get_attribute('style'):
                    if not is_one_off_check: self.known_tickets = set()
                    return []
            except NoSuchElementException:
                pass
            
            current_tickets = []
            for listing in driver.find_elements(By.XPATH, "//ul[@id='list']//twickets-listing"):
                try:
                    details_text = listing.find_element(By.XPATH, ".//span[starts-with(@id, 'listingSeatDetails')]").text.strip()
                    summary_text = listing.find_element(By.XPATH, ".//span[starts-with(@id, 'listingTicketSummary')]").text.strip()
                    price_match = re.search(r'£\s?[\d,.]+', summary_text)
                    price = price_match.group(0) if price_match else "N/A"
                    unique_id = hashlib.md5(details_text.encode()).hexdigest()
                    current_tickets.append({'id': unique_id, 'text': details_text, 'price': price})
                except Exception:
                    continue
            
            if not current_tickets:
                if not is_one_off_check: self.known_tickets = set()
                return []
            if is_one_off_check:
                return current_tickets
            
            current_ids = {t['id'] for t in current_tickets}
            if not self.known_tickets:
                self.known_tickets = current_ids
                return []
            
            new_ids = current_ids - self.known_tickets
            if new_ids:
                self.known_tickets.update(new_ids)
                return [t for t in current_tickets if t['id'] in new_ids]
            
            self.known_tickets = self.known_tickets.intersection(current_ids)
            return []
        except WebDriverException as e:
            logging.error(f"WebDriver error in check_tickets: {e.msg}")
            if not is_one_off_check: self.is_running = False
            return []
        except Exception as e:
            logging.error(f"Error in check_tickets: {e}")
            return []

    def broadcast_new_tickets(self, new_tickets, first_dibs_enabled):
        if first_dibs_enabled and self.admin_email:
            subject = f"🔔 FIRST DIBS on {len(new_tickets)} New Oasis Tickets!"
            tickets_info = "\n".join([f"Price: {t.get('price', 'N/A')}, Details: {t.get('text', '')}" for t in new_tickets])
            body = f"Hi Admin,\n\n{len(new_tickets)} new tickets listed.\n\n{tickets_info}\n\nEvent URL: {self.url}\n\nYou have {self.first_dibs_delay} seconds."
            self.send_email(self.admin_email, subject, body)
            time.sleep(self.first_dibs_delay)

        subject = f"🎸 {len(new_tickets)} New Oasis Tickets Available!"
        tickets_info = "\n".join([f"\nTicket {i+1}:\n  Price: {t.get('price', 'N/A')}\n  Details: {t.get('text', '')[:150]}...\n" for i, t in enumerate(new_tickets)])
        body = f"Hi Oasis Fan!\n\n{len(new_tickets)} NEW tickets are now available!\n\nEvent URL: {self.url}\n\n{tickets_info}\nCheck the page NOW!"
        
        recipients = list(self.subscribers)
        if first_dibs_enabled and self.admin_email:
            recipients = [s for s in recipients if s['email'].lower() != self.admin_email.lower()]
        
        for sub in recipients:
            self.send_email(sub['email'], subject, body)

    def monitor_loop(self, check_interval, first_dibs_enabled):
        total_checks, tickets_found = 0, 0
        self.is_running = True
        driver = None
        try:
            options = Options()
            options.add_argument("--disable-gpu"); options.add_argument("--headless")
            options.add_argument("--no-sandbox"); options.add_argument("--disable-dev-shm-usage")
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
            service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
            driver = webdriver.Chrome(service=service, options=options)
            logging.info("Dedicated monitoring driver initialized.")
            
            while self.is_running:
                new_tickets = self.check_tickets(driver=driver)
                total_checks += 1
                if new_tickets:
                    tickets_found += len(new_tickets)
                    self.broadcast_new_tickets(new_tickets, first_dibs_enabled)
                
                self.update_status({'is_running': True, 'last_check': datetime.now().isoformat(), 'total_checks': total_checks, 'tickets_found': tickets_found})
                time.sleep(check_interval)
        except Exception as e:
            logging.error(f"FATAL Error in monitor_loop: {e}")
        finally:
            if driver: driver.quit()
            logging.info("Dedicated monitoring driver shut down.")
            self.is_running = False
            self.update_status({'is_running': False, 'last_check': datetime.now().isoformat(), 'total_checks': total_checks, 'tickets_found': tickets_found})
            st.session_state.monitoring_active = False

def start_monitoring():
    if not st.session_state.get('monitoring_active', False):
        st.session_state.monitoring_active = True
        monitor = st.session_state.monitor
        check_interval = st.secrets.get("monitoring", {}).get("check_interval", 30)
        first_dibs = st.session_state.get("first_dibs_enabled", False)
        
        thread = threading.Thread(target=monitor.monitor_loop, args=(check_interval, first_dibs))
        thread.daemon = True
        thread.start()
        st.toast("Monitoring started!")
    else:
        st.toast("Monitoring is already active.")

def stop_monitoring():
    if st.session_state.get('monitoring_active', False):
        st.session_state.monitor.is_running = False
        st.session_state.monitoring_active = False
        st.toast("Monitoring stopping...")
    else:
        st.toast("Monitoring is not active.")

def main():
    st.set_page_config(page_title="Oasis Ticket Checker", page_icon="🎸", layout="wide")

    if 'monitor' not in st.session_state:
        try:
            st.session_state.monitor = TwicketsMonitor(
                url=st.secrets["twickets"]["url"],
                sender_email=st.secrets["email"]["sender_email"],
                sender_password=st.secrets["email"]["sender_password"],
                admin_email=st.secrets.get("admin", {}).get("email"),
                first_dibs_delay=st.secrets.get("admin", {}).get("first_dibs_delay", 90)
            )
            status = st.session_state.monitor.get_status()
            st.session_state.monitoring_active = status.get('is_running', False)
        except Exception as e:
            st.error(f"Failed to initialize. Check secrets.toml: {e}"); st.stop()
    
    monitor = st.session_state.monitor

    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Oasis_Logo.svg/1600px-Oasis_Logo.svg.png?2023026104117", use_container_width=True)
    st.title("Oasis Ticket Checker")
    
    status = monitor.get_status()
    if status.get('last_check'):
        last_check_dt = datetime.fromisoformat(status['last_check'])
        time_diff_secs = (datetime.now() - last_check_dt).total_seconds()
        is_stale = time_diff_secs > (st.secrets.get("monitoring", {}).get("check_interval", 30) * 2)
        if st.session_state.get('monitoring_active', False) and is_stale:
            status_color, time_ago = "🔴", "stalled"
        else:
            time_ago = f"{int(time_diff_secs)}s ago" if time_diff_secs < 60 else f"{int(time_diff_secs / 60)}m ago"
            status_color = "🟢"
        st.info(f"{status_color} Last check: {time_ago}")

    with st.sidebar:
        st.header("⚙️ Admin Controls")
        if not st.session_state.get('admin_authenticated', False):
            admin_password = st.text_input("Admin Password", type="password")
            if st.button("Login"):
                if authenticate_admin(admin_password): st.rerun()
                else: st.error("Invalid password")
        else:
            st.success("🔓 Admin authenticated")
            if monitor.admin_email:
                st.checkbox("🔔 Enable 'First Dibs'", key="first_dibs_enabled")
            
            st.button("🚀 Start Monitoring", on_click=start_monitoring)
            st.button("⏹️ Stop Monitoring", on_click=stop_monitoring)
            
            if st.button("🔄 Initialize Baseline"):
                with st.spinner("Checking page..."):
                    driver = get_driver()
                    baseline_tickets = monitor.check_tickets(driver=driver, is_one_off_check=True)
                    monitor.known_tickets = {t['id'] for t in baseline_tickets}
                st.success(f"✅ Baseline set with {len(monitor.known_tickets)} tickets.")

            if st.button("🚪 Logout"):
                st.session_state.admin_authenticated = False
                st.rerun()

        st.subheader("📊 Status")
        status_text = "🟢 Active" if st.session_state.get('monitoring_active', False) else "🔴 Stopped"
        st.metric("Monitoring Status", status_text)
        st.write(f"**Subscribers:** {monitor.get_subscriber_count()}")

    col1, col2 = st.columns(2)
    with col1:
        st.header("📧 Subscribe for Alerts")
        with st.form("subscription_form"):
            email = st.text_input("Email Address")
            name = st.text_input("Name (Optional)")
            if st.form_submit_button("🎸 Subscribe"):
                if email:
                    success, message = monitor.add_subscriber(email, name)
                    if success: st.success(f"🌟 {message}"); st.balloons()
                    else: st.error(message)
                else: st.error("Please enter an email address")
    with col2:
        st.header("🔕 Unsubscribe")
        with st.form("unsubscribe_form"):
            unsub_email = st.text_input("Your email address")
            if st.form_submit_button("Unsubscribe"):
                if unsub_email and monitor.remove_subscriber(unsub_email):
                    st.success("Unsubscribed successfully!")
                else: st.warning("Email not found.")

def authenticate_admin(password):
    admin_pass = st.secrets.get("admin", {}).get("password")
    if admin_pass and password == admin_pass:
        st.session_state.admin_authenticated = True
        return True
    return False

if __name__ == "__main__":
    main()
