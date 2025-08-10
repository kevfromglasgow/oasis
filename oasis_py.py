import streamlit as st
import pandas as pd
import json
import os
import threading
import time
from datetime import datetime
import logging
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import hashlib
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# File to store user subscriptions
USERS_FILE = 'subscribers.json'
STATUS_FILE = 'monitor_status.json'

class TwicketsMonitor:
    def __init__(self, url, sender_email, sender_password, admin_email=None, first_dibs_delay=90, smtp_server="smtp.gmail.com", smtp_port=587):
        self.url = url
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.known_tickets = set()
        self.is_running = False
        self.last_check = None
        self.subscribers = self.load_subscribers()
        self.session = requests.Session()
        # New attributes for 'First Dibs' feature
        self.admin_email = admin_email
        self.first_dibs_delay = first_dibs_delay
        # Set up session with headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })

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
        """Add a new subscriber"""
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
        """Check for current tickets and notify new subscriber immediately"""
        try:
            # Note: We call check_tickets, but it won't trigger notifications for others,
            # it just returns the list of available tickets.
            current_tickets = self.check_tickets() 
            if current_tickets:
                logging.info(f"Found {len(current_tickets)} current tickets for new subscriber {email}")
                self.send_welcome_email_with_current_tickets(email, name, current_tickets)
            else:
                logging.info(f"No current tickets to notify new subscriber {email}")
        except Exception as e:
            logging.error(f"Error checking current tickets for new subscriber: {e}")

    def send_welcome_email_with_current_tickets(self, email, name, tickets):
        """Send welcome email with current available tickets to new subscriber"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = email
            msg['Subject'] = f"🎸 Welcome! {len(tickets)} Oasis Tickets Currently Available!"
            
            tickets_info = ""
            for i, ticket in enumerate(tickets, 1):
                tickets_info += f"\nTicket {i}:\n"
                if ticket.get('price'):
                    tickets_info += f"  Price: {ticket['price']}\n"
                if ticket.get('text'):
                    tickets_info += f"  Details: {ticket['text'][:150]}...\n"
                tickets_info += "\n"
            
            display_name = name if name else 'Oasis Fan'
            body = f"""
Hi {display_name}!

🎸 WELCOME TO THE OASIS TICKET ALERTS! 🎸

Great news! There are currently {len(tickets)} Oasis tickets available on Twickets RIGHT NOW!

Event URL: {self.url}

CURRENT AVAILABLE TICKETS:
{tickets_info}

🚨 These tickets are live and available NOW! Don't Look Back in Anger - check the page immediately!

You'll also receive instant alerts whenever NEW tickets become available.

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

You're gonna Live Forever with these Oasis memories!
Rock and Roll Star treatment starts now! 🌟

---
Mad for It? You're all set for future alerts too!
To unsubscribe, reply with "UNSUBSCRIBE" in the subject line.
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            text = msg.as_string()
            server.sendmail(self.sender_email, email, text)
            server.quit()
            
            logging.info(f"Welcome email with current tickets sent successfully to {email}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to send welcome email to {email}: {e}")
            return False

    def remove_subscriber(self, email):
        """Remove a subscriber"""
        email = email.lower().strip()
        original_count = len(self.subscribers)
        self.subscribers = [s for s in self.subscribers if s['email'] != email]
        self.save_subscribers()
        return len(self.subscribers) < original_count

    def get_subscriber_count(self):
        """Get number of active subscribers"""
        return len(self.subscribers)

    def update_status(self, status_data):
        """Update monitoring status"""
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump(status_data, f, indent=2)
        except Exception as e:
            logging.error(f"Error updating status: {e}")

    def get_status(self):
        """Get current monitoring status"""
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, 'r') as f:
                    return json.load(f)
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}
        except Exception as e:
            logging.error(f"Error getting status: {e}")
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}

    def check_tickets(self):
        """Check if NEW tickets are available using a more robust scraping method."""
        try:
            logging.info(f"Requesting URL: {self.url}")
            response = self.session.get(self.url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            ticket_list_container = soup.find(id="list")
            no_listings_found = soup.find(id="no-listings-found")
            if not ticket_list_container or (no_listings_found and 'display: none' not in no_listings_found.get('style', '')):
                self.known_tickets = set()
                return []
            listing_elements = ticket_list_container.find_all('div', class_='listing')
            if not listing_elements:
                self.known_tickets = set()
                return []
            current_tickets = []
            for listing in listing_elements:
                try:
                    details_element = listing.select_one('[id^="listingSeatDetails"]')
                    if not details_element: continue
                    details_text = details_element.get_text(strip=True)
                    price_element = listing.find('span', class_='price')
                    price = price_element.get_text(strip=True) if price_element else "Price not found"
                    unique_id = hashlib.md5(details_text.encode()).hexdigest()
                    current_tickets.append({'id': unique_id, 'text': details_text, 'price': price})
                except Exception as e:
                    logging.warning(f"Could not parse a specific ticket listing. Error: {e}")
                    continue
            if not current_tickets:
                self.known_tickets = set()
                return []
            current_ticket_ids = {ticket['id'] for ticket in current_tickets}
            if not self.known_tickets:
                self.known_tickets = current_ticket_ids
                return [] 
            new_ticket_ids = current_ticket_ids - self.known_tickets
            if new_ticket_ids:
                new_tickets = [t for t in current_tickets if t['id'] in new_ticket_ids]
                logging.info(f"SUCCESS: Found {len(new_tickets)} new tickets!")
                self.known_tickets.update(new_ticket_ids)
                return new_tickets
            else:
                self.known_tickets = self.known_tickets.intersection(current_ticket_ids)
                return []
        except requests.RequestException as e:
            logging.error(f"Request error while checking tickets: {e}")
            return []
        except Exception as e:
            logging.error(f"An unexpected error occurred in check_tickets: {e}")
            return []

    def send_admin_first_dibs_notification(self, new_tickets):
        """Send a special 'first dibs' notification to the admin ONLY."""
        if not self.admin_email:
            logging.warning("First dibs enabled, but no admin email is configured.")
            return
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = self.admin_email
            msg['Subject'] = f"🔔 FIRST DIBS on {len(new_tickets)} New Oasis Tickets!"
            tickets_info = ""
            for i, ticket in enumerate(new_tickets, 1):
                tickets_info += f"\nTicket {i}: Price: {ticket.get('price', 'N/A')}, Details: {ticket.get('text', '')}\n"
            body = f"""
Hi Admin,

🔔 ADMIN ALERT: FIRST DIBS! 🔔

You're getting this exclusive heads-up. {len(new_tickets)} new Oasis tickets have just been listed.

{tickets_info}

Event URL: {self.url}

You have {self.first_dibs_delay} seconds before other subscribers are notified. Good luck!

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            msg.attach(MIMEText(body, 'plain'))
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, self.admin_email, msg.as_string())
            server.quit()
            logging.info(f"Admin 'First Dibs' email sent successfully to {self.admin_email}")
        except Exception as e:
            logging.error(f"Failed to send 'First Dibs' email to admin {self.admin_email}: {e}")

    def send_email_notifications(self, new_tickets, exclude_admin=False):
        """Send email notifications to subscribers."""
        if not self.subscribers:
            logging.info("No subscribers to notify")
            return
        
        recipients = self.subscribers
        if exclude_admin and self.admin_email:
            admin_email_lower = self.admin_email.lower()
            recipients = [s for s in self.subscribers if s['email'].lower() != admin_email_lower]
            logging.info(f"Excluding admin '{self.admin_email}' from general notification.")
        
        if not recipients:
            logging.info("No subscribers to notify after exclusion.")
            return

        successful_sends = 0
        failed_sends = 0
        
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
                body = f"""
Hi {name}!

🎸 BIBLICAL NEWS! 🎸

{len(new_tickets)} NEW Oasis tickets are now available on Twickets!
This could be your chance to witness the comeback of the century!

Event URL: {self.url}

{tickets_info}

🚨 IMPORTANT: These are BRAND NEW listings that weren't there before!
Don't Look Back in Anger - check the page NOW to secure your tickets before they're gone!

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

You're gonna Live Forever with these Oasis memories!
Rock and Roll Star treatment awaits! 🌟

---
Mad for It? Keep this subscription active!
To unsubscribe, reply with "UNSUBSCRIBE" in the subject line.
                """
                
                msg.attach(MIMEText(body, 'plain'))
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, subscriber['email'], msg.as_string())
                server.quit()
                successful_sends += 1
                logging.info(f"Email sent successfully to {subscriber['email']}")
            except Exception as e:
                failed_sends += 1
                logging.error(f"Failed to send email to {subscriber['email']}: {e}")
        
        logging.info(f"Email notifications complete: {successful_sends} successful, {failed_sends} failed")
        return successful_sends, failed_sends

    def monitor_loop(self, check_interval=30, first_dibs_enabled=False):
        """Main monitoring loop (runs in background thread)"""
        status = self.get_status()
        total_checks = status.get('total_checks', 0)
        tickets_found = status.get('tickets_found', 0)
        self.is_running = True
        try:
            while self.is_running:
                current_time = datetime.now()
                logging.info(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] Checking for new tickets...")
                new_tickets = self.check_tickets()
                total_checks += 1
                if new_tickets:
                    tickets_found += len(new_tickets)
                    logging.info(f"🎫 NEW TICKETS DETECTED! Found {len(new_tickets)} new tickets.")
                    if first_dibs_enabled and self.admin_email:
                        self.send_admin_first_dibs_notification(new_tickets)
                        logging.info(f"Admin notified. Waiting {self.first_dibs_delay} seconds before notifying other subscribers...")
                        time.sleep(self.first_dibs_delay)
                        logging.info("Delay finished. Notifying remaining subscribers.")
                        self.send_email_notifications(new_tickets, exclude_admin=True)
                    else:
                        self.send_email_notifications(new_tickets, exclude_admin=False)
                
                self.update_status({
                    'is_running': True,
                    'last_check': current_time.isoformat(),
                    'total_checks': total_checks,
                    'tickets_found': tickets_found,
                    'subscriber_count': len(self.subscribers)
                })
                for _ in range(check_interval):
                    if not self.is_running: break
                    time.sleep(1)
        except Exception as e:
            logging.error(f"Error in monitoring loop: {e}")
        finally:
            self.update_status({
                'is_running': False,
                'last_check': datetime.now().isoformat(),
                'total_checks': total_checks,
                'tickets_found': tickets_found,
                'subscriber_count': len(self.subscribers)
            })

monitor = None
monitor_thread = None

def init_monitor():
    """Initialize the monitor with config from secrets"""
    global monitor
    if monitor is None:
        try:
            sender_email = st.secrets["email"]["sender_email"]
            sender_password = st.secrets["email"]["sender_password"]
            url = st.secrets["twickets"]["url"]
            admin_email = st.secrets.get("admin", {}).get("email")
            first_dibs_delay = st.secrets.get("admin", {}).get("first_dibs_delay", 90)
            
            monitor = TwicketsMonitor(
                url=url,
                sender_email=sender_email,
                sender_password=sender_password,
                admin_email=admin_email,
                first_dibs_delay=first_dibs_delay
            )
        except Exception as e:
            st.error(f"Failed to initialize monitor. Please check your secrets configuration: {e}")
            return None
    return monitor

def start_monitoring():
    """Start the monitoring in a background thread"""
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
    """Stop the monitoring"""
    global monitor
    if monitor:
        monitor.is_running = False

def is_admin_authenticated():
    """Check if admin is authenticated"""
    return st.session_state.get('admin_authenticated', False)

def authenticate_admin(password):
    """Authenticate admin with password"""
    admin_password = st.secrets.get("admin", {}).get("password", "admin") # Default password if not set
    if admin_password and password == admin_password:
        st.session_state.admin_authenticated = True
        return True
    return False

def main():
    st.set_page_config(page_title="Oasis Ticket Checker", page_icon="🎸", layout="wide")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Oasis_Logo.svg/1600px-Oasis_Logo.svg.png?20230326104117", width=400)
    
    st.title("Oasis Ticket Checker")
    st.markdown("Get notified instantly when new Oasis tickets become available on Twickets!")
    
    monitor = init_monitor()
    if not monitor:
        st.stop()
    
    status = monitor.get_status()
    if status.get('last_check'):
        last_check_dt = datetime.fromisoformat(status['last_check'])
        time_diff = datetime.now() - last_check_dt
        if time_diff.total_seconds() < 60:
            time_ago = f"{int(time_diff.total_seconds())} seconds ago"
            status_color = "🟢"
        elif time_diff.total_seconds() < 3600:
            time_ago = f"{int(time_diff.total_seconds() / 60)} minutes ago"
            status_color = "🟡" if time_diff.total_seconds() > 300 else "🟢"
        else:
            time_ago = f"{int(time_diff.total_seconds() / 3600)} hours ago"
            status_color = "🔴"
        st.info(f"{status_color} **Last ticket check:** {last_check_dt.strftime('%H:%M:%S on %Y-%m-%d')} ({time_ago})")
    else:
        st.warning("⏸️ **Monitoring not started yet** - No checks performed")
    
    st.markdown("---")
    
    with st.sidebar:
        st.header("⚙️ Admin Controls")
        
        if not is_admin_authenticated():
            admin_password = st.text_input("Admin Password", type="password", key="admin_login")
            if st.button("Login"):
                if authenticate_admin(admin_password):
                    st.success("Admin authenticated!")
                    st.rerun()
                else:
                    st.error("Invalid admin password")
            st.info("Admin access required for controls")
        else:
            st.success("🔓 Admin authenticated")
            
            st.markdown("---")
            if monitor.admin_email:
                st.checkbox("🔔 Enable 'First Dibs' for Admin", key="first_dibs_enabled",
                            help=f"If enabled, a notification will be sent to {monitor.admin_email} {monitor.first_dibs_delay} seconds before other subscribers are alerted.")
            else:
                st.info("To enable 'First Dibs', add your email to the [admin] section in secrets.toml")
            st.markdown("---")
            
            if st.button("🚀 Start Monitoring"):
                if start_monitoring():
                    st.success("Monitoring started!")
                else:
                    st.info("Monitoring is already running")
            
            if st.button("🔄 Initialize Baseline"):
                if monitor:
                    st.info("Checking current tickets to establish baseline...")
                    monitor.known_tickets = set()
                    monitor.check_tickets()
                    baseline_count = len(monitor.known_tickets)
                    if baseline_count > 0:
                        st.success(f"✅ Baseline set! Found {baseline_count} existing tickets.")
                    else:
                        st.success("✅ No tickets currently available.")
                else:
                    st.error("Monitor not initialized")
            
            if st.button("⏹️ Stop Monitoring"):
                stop_monitoring()
                st.success("Monitoring stopped!")
            
            if st.button("🧪 Test Email System"):
                if monitor and monitor.subscribers:
                    test_tickets = [{'id': 'test_123', 'text': 'TEST TICKET: Oasis Live Forever Tour - Manchester Arena', 'price': '£150'}]
                    successful, failed = monitor.send_email_notifications(test_tickets)
                    if successful > 0: st.success(f"✅ Test emails sent successfully to {successful} subscribers!")
                    if failed > 0: st.error(f"❌ Failed to send {failed} test emails.")
                else:
                    st.warning("No subscribers to test with or monitor not initialized.")
            
            if st.button("🚪 Logout"):
                st.session_state.admin_authenticated = False
                st.rerun()
        
        status = monitor.get_status()
        st.subheader("📊 Status")
        st.metric("Monitoring Status", "🟢 Active" if status['is_running'] else "🔴 Stopped")
        if status.get('last_check'):
            st.write(f"**Last Check:** {datetime.fromisoformat(status['last_check']).strftime('%H:%M:%S')}")
        st.write(f"**Total Checks:** {status.get('total_checks', 0)}")
        st.write(f"**Tickets Found:** {status.get('tickets_found', 0)}")
        st.write(f"**Subscribers:** {status.get('subscriber_count', 0)}")
        
        if is_admin_authenticated():
            st.markdown("---")
            st.subheader("👥 Subscriber Management")
            subscribers = monitor.load_subscribers()
            if subscribers:
                with st.expander("View All Subscribers"):
                    df = pd.DataFrame(subscribers)
                    df['subscribed_at'] = pd.to_datetime(df['subscribed_at']).dt.strftime('%Y-%m-%d %H:%M')
                    st.dataframe(df[['name', 'email', 'subscribed_at']], use_container_width=True)
                with st.expander("Remove Subscriber"):
                    email_to_remove = st.selectbox("Select email to remove:", [s['email'] for s in subscribers])
                    if st.button("Remove Subscriber", type="secondary"):
                        if monitor.remove_subscriber(email_to_remove):
                            st.success(f"Removed {email_to_remove}")
                            st.rerun()
                        else: st.error("Email not found")
            else:
                st.info("No subscribers yet")
    
    main_col1, main_col2 = st.columns([2, 1])
    with main_col1:
        st.header("📧 Subscribe for Oasis Ticket Alerts")
        with st.form("subscription_form"):
            email = st.text_input("Email Address", placeholder="your.email@example.com")
            name = st.text_input("Name (Optional)", placeholder="Your Name")
            if st.form_submit_button("🎸 Subscribe for Oasis Tickets"):
                if email:
                    success, message = monitor.add_subscriber(email, name)
                    if success:
                        st.success(f"🌟 {message} You're **Mad for It** now!")
                        st.balloons()
                    else: st.error(message)
                else: st.error("Please enter an email address")
        
        st.header("🔕 Unsubscribe")
        with st.form("unsubscribe_form"):
            unsub_email = st.text_input("Your email address", placeholder="email@example.com")
            if st.form_submit_button("Unsubscribe"):
                if unsub_email and monitor.remove_subscriber(unsub_email):
                    st.success("Email unsubscribed successfully!")
                else: st.warning("Email not found in our subscription list.")
    
    with main_col2:
        st.header("ℹ️ How it works")
        st.markdown("1. **Subscribe** with your email\n2. Our monitor checks Twickets constantly\n3. **Get notified** instantly for NEW tickets\n4. **No spam** - only alerts for genuinely new listings")
        st.markdown("**Event Being Monitored:**")
        if 'url' in st.secrets.get("twickets", {}):
            st.markdown(f"🎸 [View Oasis Event on Twickets]({st.secrets['twickets']['url']})")
        st.markdown("---")
        st.subheader("🎸 Supersonic Fans")
        subscriber_count = monitor.get_subscriber_count()
        if subscriber_count > 0:
            st.success(f"🌟 **{subscriber_count} Supersonic fans** are already subscribed!")
        else:
            st.info("**Be the first Supersonic fan to subscribe!** 🚀")
        st.markdown("---")
        st.caption("🔒 **Privacy**: Your email is only used for ticket alerts.")

if __name__ == "__main__":
    main()
