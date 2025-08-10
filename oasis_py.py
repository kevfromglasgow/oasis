import streamlit as st
import pandas as pd
import json
import os
import threading
import time
from datetime import datetime
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, WebDriverException
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re

# For Streamlit Cloud compatibility
try:
    import chromedriver_autoinstaller
    chromedriver_autoinstaller.install()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('twickets_monitor.log'),
        logging.StreamHandler()
    ]
)

# File to store user subscriptions
USERS_FILE = 'subscribers.json'
STATUS_FILE = 'monitor_status.json'

class TwicketsMonitor:
    def __init__(self, url, sender_email, sender_password, smtp_server="smtp.gmail.com", smtp_port=587):
        self.url = url
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.driver = None
        self.known_tickets = set()
        self.is_running = False
        self.last_check = None
        self.subscribers = self.load_subscribers()
        
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
        # Check if email already exists
        for subscriber in self.subscribers:
            if subscriber['email'] == email:
                return False, "Email already subscribed"
        
        # Validate email format
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return False, "Invalid email format"
        
        self.subscribers.append({
            'email': email,
            'name': name,
            'subscribed_at': datetime.now().isoformat()
        })
        self.save_subscribers()
        return True, "Successfully subscribed!"
    
    def remove_subscriber(self, email):
        """Remove a subscriber"""
        email = email.lower().strip()
        self.subscribers = [s for s in self.subscribers if s['email'] != email]
        self.save_subscribers()
    
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
            return {
                'is_running': False,
                'last_check': None,
                'total_checks': 0,
                'tickets_found': 0
            }
        except Exception as e:
            logging.error(f"Error getting status: {e}")
            return {'is_running': False, 'last_check': None, 'total_checks': 0, 'tickets_found': 0}
    
    def setup_driver(self):
        """Setup Chrome driver with headless options for Streamlit Cloud"""
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--remote-debugging-port=9222')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--allow-running-insecure-content')
            chrome_options.add_argument('--disable-features=VizDisplayCompositor')
            chrome_options.add_argument('--disable-background-timer-throttling')
            chrome_options.add_argument('--disable-backgrounding-occluded-windows')
            chrome_options.add_argument('--disable-renderer-backgrounding')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            
            # For Streamlit Cloud - try webdriver-manager first
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                from selenium.webdriver.chrome.service import Service
                
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logging.info("Chrome driver initialized with webdriver-manager")
                return True
            except Exception as e:
                logging.warning(f"webdriver-manager failed: {e}")
                
                # Fallback to system Chrome
                chrome_paths = [
                    '/usr/bin/chromium',
                    '/usr/bin/chromium-browser', 
                    '/usr/bin/google-chrome',
                    '/usr/bin/google-chrome-stable',
                    '/snap/bin/chromium'
                ]
                
                for chrome_path in chrome_paths:
                    if os.path.exists(chrome_path):
                        chrome_options.binary_location = chrome_path
                        logging.info(f"Found Chrome at: {chrome_path}")
                        break
                
                self.driver = webdriver.Chrome(options=chrome_options)
                logging.info("Chrome driver initialized with system Chrome")
                return True
                
        except Exception as e:
            logging.error(f"Failed to initialize Chrome driver: {e}")
            st.error(f"⚠️ Browser setup failed. This might be a temporary issue with Streamlit Cloud. Error: {e}")
            return False
    
    def get_ticket_details(self):
        """Extract ticket details to create unique identifiers"""
        ticket_details = []
        try:
            ticket_selectors = [
                '//*[@id="list"]//div[contains(@class, "listing")]',
                '//*[@id="list"]//div[contains(@class, "ticket")]',
                '//*[@id="list"]//div[contains(@class, "item")]',
                '//*[@id="list"]//li',
                '//*[@id="list"]//*[contains(@data-testid, "listing")]'
            ]
            
            for selector in ticket_selectors:
                tickets = self.driver.find_elements(By.XPATH, selector)
                if tickets:
                    for ticket in tickets:
                        try:
                            ticket_text = ticket.text.strip()
                            ticket_id = ticket.get_attribute('data-id') or ticket.get_attribute('id')
                            
                            price_elements = ticket.find_elements(By.XPATH, './/*[contains(@class, "price") or contains(text(), "£") or contains(text(), "$")]')
                            price = price_elements[0].text.strip() if price_elements else ""
                            
                            section_elements = ticket.find_elements(By.XPATH, './/*[contains(@class, "section") or contains(@class, "seat") or contains(@class, "block")]')
                            section = section_elements[0].text.strip() if section_elements else ""
                            
                            unique_id = f"{ticket_id}_{price}_{section}_{ticket_text[:50]}"
                            ticket_details.append({
                                'id': unique_id,
                                'text': ticket_text,
                                'price': price,
                                'section': section
                            })
                        except Exception as e:
                            logging.debug(f"Error extracting ticket detail: {e}")
                            continue
                    break
                    
        except Exception as e:
            logging.error(f"Error getting ticket details: {e}")
            
        return ticket_details

    def check_tickets(self):
        """Check if NEW tickets are available on the page"""
        try:
            self.driver.get(self.url)
            time.sleep(3)
            
            try:
                no_listings = self.driver.find_element(By.XPATH, '//*[@id="no-listings-found"]')
                if no_listings.is_displayed():
                    logging.info("No tickets available")
                    return []
            except NoSuchElementException:
                pass
            
            current_tickets = self.get_ticket_details()
            
            if not current_tickets:
                try:
                    ticket_list = self.driver.find_element(By.XPATH, '//*[@id="list"]')
                    if ticket_list:
                        buy_buttons = self.driver.find_elements(By.XPATH, '//*[@id="list"]//button[contains(@class, "buy") or contains(text(), "Buy")]')
                        if buy_buttons:
                            current_tickets = [{'id': f'generic_{i}', 'text': f'Ticket {i+1}'} for i in range(len(buy_buttons))]
                except NoSuchElementException:
                    pass
            
            if current_tickets:
                current_ticket_ids = {ticket['id'] for ticket in current_tickets}
                new_ticket_ids = current_ticket_ids - self.known_tickets
                
                if new_ticket_ids:
                    new_tickets = [t for t in current_tickets if t['id'] in new_ticket_ids]
                    logging.info(f"Found {len(new_tickets)} new tickets!")
                    self.known_tickets = current_ticket_ids
                    return new_tickets
                else:
                    logging.info("No new tickets (same tickets as before)")
                    return []
            else:
                logging.info("No tickets available")
                return []
            
        except Exception as e:
            logging.error(f"Error checking tickets: {e}")
            return []

    def send_email_notifications(self, new_tickets):
        """Send email notifications to all subscribers"""
        if not self.subscribers:
            logging.info("No subscribers to notify")
            return
        
        successful_sends = 0
        failed_sends = 0
        
        for subscriber in self.subscribers:
            try:
                msg = MIMEMultipart()
                msg['From'] = self.sender_email
                msg['To'] = subscriber['email']
                msg['Subject'] = f"🎸 {len(new_tickets)} New Oasis Tickets Available on Twickets!"
                
                tickets_info = ""
                for i, ticket in enumerate(new_tickets, 1):
                    tickets_info += f"\nTicket {i}:\n"
                    if ticket.get('price'):
                        tickets_info += f"  Price: {ticket['price']}\n"
                    if ticket.get('section'):
                        tickets_info += f"  Section: {ticket['section']}\n"
                    if ticket.get('text') and len(ticket['text']) > 10:
                        tickets_info += f"  Details: {ticket['text'][:100]}...\n"
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
                text = msg.as_string()
                server.sendmail(self.sender_email, subscriber['email'], text)
                server.quit()
                
                successful_sends += 1
                logging.info(f"Email sent successfully to {subscriber['email']}")
                
            except Exception as e:
                failed_sends += 1
                logging.error(f"Failed to send email to {subscriber['email']}: {e}")
        
        logging.info(f"Email notifications complete: {successful_sends} successful, {failed_sends} failed")
        return successful_sends, failed_sends

    def monitor_loop(self, check_interval=30):
        """Main monitoring loop (runs in background thread)"""
        if not self.setup_driver():
            logging.error("Failed to setup driver")
            return
        
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
                    logging.info(f"🎫 NEW TICKETS DETECTED! Found {len(new_tickets)} new tickets. Sending notifications...")
                    successful, failed = self.send_email_notifications(new_tickets)
                
                # Update status
                self.update_status({
                    'is_running': True,
                    'last_check': current_time.isoformat(),
                    'total_checks': total_checks,
                    'tickets_found': tickets_found,
                    'subscriber_count': len(self.subscribers)
                })
                
                # Wait for next check
                for _ in range(check_interval):
                    if not self.is_running:
                        break
                    time.sleep(1)
                
        except Exception as e:
            logging.error(f"Error in monitoring loop: {e}")
        finally:
            if self.driver:
                self.driver.quit()
            self.update_status({
                'is_running': False,
                'last_check': datetime.now().isoformat(),
                'total_checks': total_checks,
                'tickets_found': tickets_found,
                'subscriber_count': len(self.subscribers)
            })

# Global monitor instance
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
            
            monitor = TwicketsMonitor(
                url=url,
                sender_email=sender_email,
                sender_password=sender_password
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
            monitor_thread = threading.Thread(target=monitor.monitor_loop, args=(check_interval,))
            monitor_thread.daemon = True
            monitor_thread.start()
            return True
    return False

def stop_monitoring():
    """Stop the monitoring"""
    global monitor
    if monitor:
        monitor.is_running = False

def main():
    st.set_page_config(
        page_title="Oasis Ticket Checker",
        page_icon="🎸",
        layout="wide"
    )
    
    # Header with logo
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Oasis_Logo.svg/1600px-Oasis_Logo.svg.png?20230326104117", 
                 width=400)
    
    st.title("Oasis Ticket Checker")
    st.markdown("Get notified instantly when new Oasis tickets become available on Twickets!")
    
    # Initialize monitor
    monitor = init_monitor()
    if not monitor:
        st.stop()
    
    # Sidebar for admin controls
    with st.sidebar:
        st.header("⚙️ Admin Controls")
        
        if st.button("🚀 Start Monitoring"):
            if start_monitoring():
                st.success("Monitoring started!")
            else:
                st.info("Monitoring is already running")
        
        if st.button("⏹️ Stop Monitoring"):
            stop_monitoring()
            st.success("Monitoring stopped!")
        
        # Status display
        status = monitor.get_status()
        st.subheader("📊 Status")
        
        if status['is_running']:
            st.success("🟢 Active")
        else:
            st.error("🔴 Stopped")
        
        if status.get('last_check'):
            last_check = datetime.fromisoformat(status['last_check'])
            st.write(f"**Last Check:** {last_check.strftime('%H:%M:%S')}")
        
        st.write(f"**Total Checks:** {status.get('total_checks', 0)}")
        st.write(f"**Tickets Found:** {status.get('tickets_found', 0)}")
        st.write(f"**Subscribers:** {status.get('subscriber_count', 0)}")
        
        # Add Oasis-themed styling
        st.markdown("---")
        st.markdown("🎸 **Definitely Maybe** you'll get tickets!")
        st.markdown("🎤 **Don't Look Back in Anger** if you miss them...")
        st.markdown("⭐ **Live Forever** with Oasis memories!")
    
    # Main content
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📧 Subscribe for Oasis Ticket Alerts")
        st.markdown("**Don't miss out on the comeback of the century!**")
        
        with st.form("subscription_form"):
            email = st.text_input("Email Address", placeholder="your.email@example.com")
            name = st.text_input("Name (Optional)", placeholder="Your Name")
            
            submitted = st.form_submit_button("🎸 Subscribe for Oasis Tickets")
            
            if submitted:
                if email:
                    success, message = monitor.add_subscriber(email, name)
                    if success:
                        st.success(f"🌟 {message} You're **Mad for It** now!")
                        st.balloons()
                    else:
                        st.error(message)
                else:
                    st.error("Please enter an email address")
        
        # Unsubscribe section
        st.header("🔕 Unsubscribe")
        with st.form("unsubscribe_form"):
            unsub_email = st.text_input("Email to unsubscribe", placeholder="email@example.com")
            unsub_submitted = st.form_submit_button("Unsubscribe")
            
            if unsub_submitted and unsub_email:
                monitor.remove_subscriber(unsub_email)
                st.success("Email unsubscribed successfully! **Stop Crying Your Heart Out** - you can always re-subscribe!")
    
    with col2:
        st.header("ℹ️ How it works")
        st.markdown("""
        1. **Subscribe** with your email address
        2. Our monitor checks for new Oasis tickets every 30 seconds
        3. **Get notified** instantly when NEW tickets appear
        4. **No spam** - only alerts for genuinely new listings
        5. **Rock and Roll Star** treatment for all subscribers!
        
        **Oasis Event Being Monitored:**
        """)
        
        if 'url' in st.secrets.get("twickets", {}):
            event_url = st.secrets["twickets"]["url"]
            st.markdown(f"🎸 [View Oasis Event on Twickets]({event_url})")
        
        st.markdown("---")
        st.subheader("📋 Current Subscribers")
        st.markdown("**All the people who believe in Oasis tickets:**")
        
        subscribers = monitor.load_subscribers()
        if subscribers:
            df = pd.DataFrame(subscribers)
            df['subscribed_at'] = pd.to_datetime(df['subscribed_at']).dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(df[['name', 'email', 'subscribed_at']], use_container_width=True)
        else:
            st.info("**Waiting for Supersonic fans to subscribe!** 🚀")

if __name__ == "__main__":
    main()
