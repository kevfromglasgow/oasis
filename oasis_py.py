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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# File to store user subscriptions and status
USERS_FILE = 'subscribers.json'
STATUS_FILE = 'monitor_status.json'

# NEW: Create a global lock for the Selenium driver to ensure thread safety
SELENIUM_LOCK = threading.Lock()


# This is cached so it's only created once per Streamlit session
@st.cache_resource
def get_driver():
    """Sets up and returns a Selenium Chrome driver."""
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
    
    service = Service(
        ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()
    )
    
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
        self.driver = None # Driver will be initialized inside the monitoring loop

    def load_subscribers(self):
        """Load subscribers from file"""
        try:
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'r') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logging.error(f"Error loading subscribers: {e}")
            return []

    def save_subscribers(self):
        """Save subscribers to file"""
        try:
            with open(USERS_FILE, 'w') as f:
                json.dump(self.subscribers, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving subscribers: {e}")

    def add_subscriber(self, email, name=""):
        email = email.lower().strip()
        for subscriber in self.subscribers:
            if subscriber['email'] == email:
                return False, "Email already subscribed"
        
        self.subscribers.append({
            'email': email,
            'name': name,
            'subscribed_at': datetime.now().isoformat()
        })
        self.save_subscribers()
        
        self.notify_new_subscriber_of_current_tickets(email, name)
        return True, "Successfully subscribed!"

    def notify_new_subscriber_of_current_tickets(self, email, name):
        """Check for current tickets and notify new subscriber immediately."""
        try:
            temp_driver = get_driver() # Get the cached driver for a one-off check
            current_tickets = self.check_tickets(driver=temp_driver, is_one_off_check=True)
            if current_tickets:
                logging.info(f"Found {len(current_tickets)} current tickets for new subscriber {email}")
                self.send_welcome_email_with_current_tickets(email, name, current_tickets)
            else:
                logging.info(f"No current tickets. Sending welcome confirmation to new subscriber {email}")
                self.send_welcome_confirmation_email(email, name)
        except Exception as e:
            logging.error(f"Error during one-off check for new subscriber: {e}")

    def send_welcome_email_with_current_tickets(self, email, name, tickets):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = email
            msg['Subject'] = f"🎸 Welcome! {len(tickets)} Oasis Tickets Currently Available!"
            tickets_info = ""
            for i, ticket in enumerate(tickets, 1):
                tickets_info += f"\nTicket {i}:\n"
                if ticket.get('price'): tickets_info += f"  Price: {ticket['price']}\n"
                if ticket.get('text'): tickets_info += f"  Details: {ticket['text'][:150]}...\n"
                tickets_info += "\n"
            display_name = name if name else 'Oasis Fan'
            body = f"Hi {display_name}!\n\n🎸 WELCOME TO THE OASIS TICKET ALERTS! 🎸\n\nGreat news! There are currently {len(tickets)} Oasis tickets available on Twickets RIGHT NOW!\n\nEvent URL: {self.url}\n\nCURRENT AVAILABLE TICKETS:\n{tickets_info}\n🚨 These tickets are live and available NOW! Don't Look Back in Anger - check the page immediately!\n\nYou'll also receive instant alerts whenever NEW tickets become available.\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nYou're gonna Live Forever with these Oasis memories!\nRock and Roll Star treatment starts now! 🌟\n\n---\nMad for It? You're all set for future alerts too!\nTo unsubscribe, reply with \"UNSUBSCRIBE\" in the subject line."
            msg.attach(MIMEText(body, 'plain'))
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, email, msg.as_string())
            server.quit()
        except Exception as e:
            logging.error(f"Failed to send welcome email to {email}: {e}")

    def send_welcome_confirmation_email(self, email, name):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = email
            msg['Subject'] = "✅ You're Subscribed to Oasis Ticket Alerts!"
            display_name = name if name else 'Oasis Fan'
            body = f"Hi {display_name}!\n\n🎸 WELCOME TO THE OASIS TICKET ALERTS! 🎸\n\nYou're all set! We've successfully added you to the notification list.\n\nThere are no tickets available right now, but don't worry – you're in the queue. The moment new tickets are listed, you'll receive an instant email alert from us.\n\nStay tuned, and get ready to witness the comeback!\n\nTime of subscription: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nYou're gonna Live Forever with these Oasis memories!\nRock and Roll Star treatment is on the way! 🌟\n\n---\nTo unsubscribe, reply with \"UNSUBSCRIBE\" in the subject line."
            msg.attach(MIMEText(body, 'plain'))
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, email, msg.as_string())
            server.quit()
        except Exception as e:
            logging.error(f"Failed to send welcome confirmation email to {email}: {e}")

    def remove_subscriber(self, email):
        email = email.lower().strip()
        original_count = len(self.subscribers)
        self.subscribers = [s for s in self.subscribers if s['email'] != email]
        self.save_subscribers()
        return len(self.subscribers) < original_count

    def get_subscriber_count(self):
        return len(self.subscribers)

    def update_status(self, status_data):
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump(status_data, f, indent=2)
        except Exception as e:
            logging.error(f"Error updating status: {e}")

    def get_status(self):
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, 'r') as f:
                    return json.load(f)
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}
        except Exception as e:
            logging.error(f"Error getting status: {e}")
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}

    def check_tickets(self, driver, is_one_off_check=False):
        """
        Check for new tickets using a Selenium driver, protected by a lock
        to ensure thread safety.
        """
        with SELENIUM_LOCK:
            try:
                driver.get(self.url)
                time.sleep(3) 

                try:
                    no_listings = driver.find_element(By.ID, 'no-listings-found')
                    if 'display: none' not in no_listings.get_attribute('style'):
                        logging.info("No tickets available ('no-listings-found' is visible).")
                        if not is_one_off_check: self.known_tickets = set()
                        return []
                except NoSuchElementException:
                    pass

                current_tickets = []
                listing_elements = driver.find_elements(By.XPATH, "//ul[@id='list']//twickets-listing")
                
                for listing in listing_elements:
                    try:
                        details_element = listing.find_element(By.XPATH, ".//span[starts-with(@id, 'listingSeatDetails')]")
                        details_text = details_element.text.strip()
                        
                        price = "Price not found"
                        summary_element = listing.find_element(By.XPATH, ".//span[starts-with(@id, 'listingTicketSummary')]")
                        summary_text = summary_element.text.strip()
                        price_match = re.search(r'£\s?[\d,.]+', summary_text)
                        if price_match: price = price_match.group(0)

                        unique_id = hashlib.md5(details_text.encode()).hexdigest()
                        current_tickets.append({'id': unique_id, 'text': details_text, 'price': price})
                    except Exception:
                        continue 

                if not current_tickets:
                    logging.info("No valid ticket elements found on page.")
                    if not is_one_off_check: self.known_tickets = set()
                    return []
                
                if is_one_off_check:
                    return current_tickets
                    
                current_ticket_ids = {ticket['id'] for ticket in current_tickets}
                if not self.known_tickets:
                    logging.info(f"Establishing baseline with {len(current_ticket_ids)} found tickets.")
                    self.known_tickets = current_ticket_ids
                    return [] 
                
                new_ticket_ids = current_ticket_ids - self.known_tickets
                if new_ticket_ids:
                    new_tickets = [t for t in current_tickets if t['id'] in new_ticket_ids]
                    logging.info(f"SUCCESS: Found {len(new_tickets)} new tickets!")
                    self.known_tickets.update(new_ticket_ids)
                    return new_tickets
                else:
                    logging.info("No new tickets found.")
                    self.known_tickets = self.known_tickets.intersection(current_ticket_ids)
                    return []
            except WebDriverException as e:
                logging.error(f"WebDriver error checking tickets: {e.msg}")
                st.error("Browser session may have crashed. Consider rebooting the app if errors persist.")
                self.is_running = False
                return []
            except Exception as e:
                logging.error(f"Unexpected error in check_tickets: {e}")
                return []
    
    def send_admin_first_dibs_notification(self, new_tickets):
        if not self.admin_email: return
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = self.admin_email
            msg['Subject'] = f"🔔 FIRST DIBS on {len(new_tickets)} New Oasis Tickets!"
            tickets_info = ""
            for i, ticket in enumerate(new_tickets, 1):
                tickets_info += f"\nTicket {i}: Price: {ticket.get('price', 'N/A')}, Details: {ticket.get('text', '')}\n"
            body = f"Hi Admin,\n\n🔔 ADMIN ALERT: FIRST DIBS! 🔔\n\nYou're getting this exclusive heads-up. {len(new_tickets)} new Oasis tickets have just been listed.\n\n{tickets_info}\nEvent URL: {self.url}\n\nYou have {self.first_dibs_delay} seconds before other subscribers are notified. Good luck!\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            msg.attach(MIMEText(body, 'plain'))
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, self.admin_email, msg.as_string())
            server.quit()
        except Exception as e:
            logging.error(f"Failed to send 'First Dibs' email to admin {self.admin_email}: {e}")

    def send_email_notifications(self, new_tickets, exclude_admin=False):
        if not self.subscribers: return
        recipients = list(self.subscribers)
        if exclude_admin and self.admin_email:
            recipients = [s for s in recipients if s['email'].lower() != self.admin_email.lower()]
        if not recipients: return
        for subscriber in recipients:
            try:
                msg = MIMEMultipart()
                msg['From'] = self.sender_email
                msg['To'] = subscriber['email']
                msg['Subject'] = f"🎸 {len(new_tickets)} New Oasis Tickets Available on Twickets!"
                tickets_info = ""
                for i, ticket in enumerate(new_tickets, 1):
                    tickets_info += f"\nTicket {i}:\n"
                    if ticket.get('price'): tickets_info += f"  Price: {ticket['price']}\n"
                    if ticket.get('text'): tickets_info += f"  Details: {ticket['text'][:150]}...\n"
                    tickets_info += "\n"
                name = subscriber.get('name', 'Oasis Fan')
                body = f"Hi {name}!\n\n🎸 BIBLICAL NEWS! 🎸\n\n{len(new_tickets)} NEW Oasis tickets are now available on Twickets!\nThis could be your chance to witness the comeback of the century!\n\nEvent URL: {self.url}\n\n{tickets_info}\n🚨 IMPORTANT: These are BRAND NEW listings that weren't there before!\nDon't Look Back in Anger - check the page NOW to secure your tickets before they're gone!\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nYou're gonna Live Forever with these Oasis memories!\nRock and Roll Star treatment awaits! 🌟\n\n---\nMad for It? Keep this subscription active!\nTo unsubscribe, reply with \"UNSUBSCRIBE\" in the subject line."
                msg.attach(MIMEText(body, 'plain'))
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, subscriber['email'], msg.as_string())
                server.quit()
            except Exception as e:
                logging.error(f"Failed to send email to {subscriber['email']}: {e}")

    def monitor_loop(self, check_interval=30, first_dibs_enabled=False):
        """Main monitoring loop using Selenium."""
        status = self.get_status()
        total_checks = status.get('total_checks', 0)
        tickets_found = status.get('tickets_found', 0)
        self.is_running = True
        
        try:
            driver = get_driver()
            logging.info("Selenium driver successfully referenced for monitoring loop.")
            
            while self.is_running:
                current_time = datetime.now()
                logging.info(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] Checking for new tickets...")
                
                new_tickets = self.check_tickets(driver=driver)
                total_checks += 1
                
                if new_tickets:
                    tickets_found += len(new_tickets)
                    logging.info(f"🎫 NEW TICKETS DETECTED! Found {len(new_tickets)} new tickets.")
                    if first_dibs_enabled and self.admin_email:
                        self.send_admin_first_dibs_notification(new_tickets)
                        time.sleep(self.first_dibs_delay)
                        self.send_email_notifications(new_tickets, exclude_admin=True)
                    else:
                        self.send_email_notifications(new_tickets)
                
                self.update_status({'is_running': True, 'last_check': current_time.isoformat(), 'total_checks': total_checks, 'tickets_found': tickets_found, 'subscriber_count': len(self.subscribers)})
                for _ in range(check_interval):
                    if not self.is_running: break
                    time.sleep(1)
        except Exception as e:
            logging.error(f"Error in monitoring loop: {e}")
        finally:
            self.update_status({'is_running': False, 'last_check': datetime.now().isoformat(), 'total_checks': total_checks, 'tickets_found': tickets_found, 'subscriber_count': len(self.subscribers)})

# --- GLOBAL FUNCTIONS FOR STREAMLIT ---
monitor = None
monitor_thread = None

def init_monitor():
    global monitor
    if monitor is None:
        try:
            sender_email = st.secrets["email"]["sender_email"]
            sender_password = st.secrets["email"]["sender_password"]
            url = st.secrets["twickets"]["url"]
            admin_email = st.secrets.get("admin", {}).get("email")
            first_dibs_delay = st.secrets.get("admin", {}).get("first_dibs_delay", 90)
            
            monitor = TwicketsMonitor(
                url=url, sender_email=sender_email, sender_password=sender_password,
                admin_email=admin_email, first_dibs_delay=first_dibs_delay
            )
        except Exception as e:
            st.error(f"Failed to initialize monitor. Check secrets: {e}")
            return None
    return monitor

def start_monitoring():
    global monitor_thread
    if monitor_thread is None or not monitor_thread.is_alive():
        monitor = init_monitor()
        if monitor:
            check_interval = st.secrets.get("monitoring", {}).get("check_interval", 30)
            first_dibs_enabled = st.session_state.get("first_dibs_enabled", False)
            monitor_thread = threading.Thread(
                target=monitor.monitor_loop, 
                args=(check_interval, first_dibs_enabled)
            )
            monitor_thread.daemon = True
            monitor_thread.start()
            return True
    return False

def stop_monitoring():
    global monitor
    if monitor:
        monitor.is_running = False

def is_admin_authenticated():
    return st.session_state.get('admin_authenticated', False)

def authenticate_admin(password):
    admin_password = st.secrets.get("admin", {}).get("password", "admin")
    if admin_password and password == admin_password:
        st.session_state.admin_authenticated = True
        return True
    return False

# --- MAIN STREAMLIT APP UI ---
def main():
    st.set_page_config(page_title="Oasis Ticket Checker", page_icon="🎸", layout="wide")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2: st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Oasis_Logo.svg/1600px-Oasis_Logo.svg.png?20230326104117", width=400)
    st.title("Oasis Ticket Checker")
    st.markdown("Get notified instantly when new Oasis tickets become available on Twickets!")
    
    monitor = init_monitor()
    if not monitor: st.stop()
    
    status = monitor.get_status()
    if status.get('last_check'):
        last_check_dt = datetime.fromisoformat(status['last_check'])
        time_diff = datetime.now() - last_check_dt
        if time_diff.total_seconds() < 60:
            time_ago, status_color = f"{int(time_diff.total_seconds())}s ago", "🟢"
        elif time_diff.total_seconds() < 3600:
            time_ago, status_color = f"{int(time_diff.total_seconds() / 60)}m ago", "🟢" if time_diff.total_seconds() < 300 else "🟡"
        else:
            time_ago, status_color = f"{int(time_diff.total_seconds() / 3600)}h ago", "🔴"
        st.info(f"{status_color} **Last check:** {last_check_dt.strftime('%H:%M:%S')} ({time_ago})")
    else:
        st.warning("⏸️ **Monitoring not started yet**")
    
    st.markdown("---")
    
    with st.sidebar:
        st.header("⚙️ Admin Controls")
        if not is_admin_authenticated():
            admin_password = st.text_input("Admin Password", type="password", key="admin_login")
            if st.button("Login"):
                if authenticate_admin(admin_password):
                    st.success("Admin authenticated!"); st.rerun()
                else:
                    st.error("Invalid admin password")
        else:
            st.success("🔓 Admin authenticated")
            if monitor.admin_email:
                st.checkbox("🔔 Enable 'First Dibs' for Admin", key="first_dibs_enabled", help=f"Notify {monitor.admin_email} {monitor.first_dibs_delay}s before others.")
            
            if st.button("🚀 Start Monitoring"):
                if start_monitoring():
                    st.success("Monitoring started with Selenium!")
                else:
                    st.info("Monitoring is already running")
            
            if st.button("🔄 Initialize Baseline"):
                if monitor:
                    with st.spinner("Initializing driver and checking page..."):
                        temp_driver = get_driver()
                        baseline_tickets = monitor.check_tickets(driver=temp_driver, is_one_off_check=True)
                        baseline_count = len(baseline_tickets)
                        monitor.known_tickets = {t['id'] for t in baseline_tickets}
                    if baseline_count > 0:
                        st.success(f"✅ Baseline set! Found {baseline_count} existing tickets.")
                    else:
                        st.success("✅ No tickets currently available.")
            
            if st.button("⏹️ Stop Monitoring"):
                stop_monitoring(); st.success("Monitoring stopped!")
            
            if st.button("🚪 Logout"):
                st.session_state.admin_authenticated = False; st.rerun()

        status = monitor.get_status()
        st.subheader("📊 Status")
        st.metric("Monitoring Status", "🟢 Active" if status.get('is_running') else "🔴 Stopped")
        if status.get('last_check'):
            st.write(f"**Last Check:** {datetime.fromisoformat(status['last_check']).strftime('%H:%M:%S')}")
        st.write(f"**Total Checks:** {status.get('total_checks', 0)}")
        st.write(f"**Tickets Found:** {status.get('tickets_found', 0)}")
        st.write(f"**Subscribers:** {monitor.get_subscriber_count()}")

    main_col1, main_col2 = st.columns([2, 1])
    with main_col1:
        st.header("📧 Subscribe for Oasis Ticket Alerts")
        with st.form("subscription_form"):
            email = st.text_input("Email Address")
            name = st.text_input("Name (Optional)")
            if st.form_submit_button("🎸 Subscribe for Oasis Tickets"):
                if email:
                    success, message = monitor.add_subscriber(email, name)
                    if success: st.success(f"🌟 {message}"); st.balloons()
                    else: st.error(message)
                else: st.error("Please enter an email address")
        
        st.header("🔕 Unsubscribe")
        with st.form("unsubscribe_form"):
            unsub_email = st.text_input("Your email address")
            if st.form_submit_button("Unsubscribe"):
                if unsub_email and monitor.remove_subscriber(unsub_email):
                    st.success("Email unsubscribed successfully!")
                else: st.warning("Email not found.")
    
    with main_col2:
        st.header("ℹ️ How it works")
        st.markdown("1. **Subscribe** with your email\n2. Our monitor checks Twickets using a real browser\n3. **Get notified** instantly for NEW tickets")
        st.markdown("**Event Being Monitored:**")
        if 'url' in st.secrets.get("twickets", {}):
            st.markdown(f"🎸 [View on Twickets]({st.secrets['twickets']['url']})")
        st.markdown("---")
        st.subheader("🎸 Supersonic Fans")
        subscriber_count = monitor.get_subscriber_count()
        if subscriber_count > 0:
            st.success(f"🌟 **{subscriber_count}** fans are subscribed!")
        else:
            st.info("Be the first to subscribe! 🚀")

if __name__ == "__main__":
    main()
