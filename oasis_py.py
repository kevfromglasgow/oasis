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
import re
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
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
        self.known_tickets = set()
        self.is_running = False
        self.last_check = None
        self.subscribers = self.load_subscribers()
        self.session = requests.Session()
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
        original_count = len(self.subscribers)
        self.subscribers = [s for s in self.subscribers if s['email'] != email]
        self.save_subscribers()
        return len(self.subscribers) < original_count  # Return True if someone was actually removed
    
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

    def check_tickets(self):
        """Check if NEW tickets are available using HTTP requests"""
        try:
            # Make request to the page
            response = self.session.get(self.url, timeout=10)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check for "no listings found" message
            no_listings = soup.find(id="no-listings-found")
            if no_listings and no_listings.is_displayed if hasattr(no_listings, 'is_displayed') else True:
                logging.info("No tickets available")
                return []
            
            # Look for ticket listings
            current_tickets = []
            ticket_list = soup.find(id="list")
            
            if ticket_list:
                # Look for various ticket elements
                ticket_elements = (
                    ticket_list.find_all('div', class_=lambda x: x and 'listing' in x.lower()) +
                    ticket_list.find_all('div', class_=lambda x: x and 'ticket' in x.lower()) +
                    ticket_list.find_all('li') +
                    ticket_list.find_all('div', class_=lambda x: x and 'item' in x.lower())
                )
                
                for i, element in enumerate(ticket_elements):
                    try:
                        # Extract text content
                        text_content = element.get_text(strip=True)
                        
                        # Skip if too short or empty
                        if len(text_content) < 10:
                            continue
                            
                        # Look for price indicators
                        price_match = re.search(r'[£$€]\s*\d+', text_content)
                        price = price_match.group() if price_match else ""
                        
                        # Create unique identifier
                        unique_id = hashlib.md5(f"{text_content}_{price}".encode()).hexdigest()[:16]
                        
                        current_tickets.append({
                            'id': unique_id,
                            'text': text_content[:200],  # Limit text length
                            'price': price
                        })
                        
                    except Exception as e:
                        logging.debug(f"Error processing ticket element: {e}")
                        continue
            
            # Check for new tickets
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
                logging.info("No tickets found")
                return []
            
        except requests.RequestException as e:
            logging.error(f"Request error: {e}")
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
                    if ticket.get('text'):
                        tickets_info += f"  Details: {ticket['text'][:150]}...\n"
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

def is_admin_authenticated():
    """Check if admin is authenticated"""
    return st.session_state.get('admin_authenticated', False)

def authenticate_admin(password):
    """Authenticate admin with password"""
    admin_password = st.secrets.get("admin", {}).get("password", None)
    if admin_password and password == admin_password:
        st.session_state.admin_authenticated = True
        return True
    return False

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
    
    # Show last check time prominently at the top
    status = monitor.get_status()
    if status.get('last_check'):
        last_check = datetime.fromisoformat(status['last_check'])
        time_diff = datetime.now() - last_check
        
        if time_diff.total_seconds() < 60:
            time_ago = f"{int(time_diff.total_seconds())} seconds ago"
            status_color = "🟢"
        elif time_diff.total_seconds() < 3600:
            time_ago = f"{int(time_diff.total_seconds() / 60)} minutes ago"
            status_color = "🟡" if time_diff.total_seconds() > 300 else "🟢"
        else:
            time_ago = f"{int(time_diff.total_seconds() / 3600)} hours ago"
            status_color = "🔴"
        
        st.info(f"{status_color} **Last ticket check:** {last_check.strftime('%H:%M:%S on %Y-%m-%d')} ({time_ago})")
    else:
        st.warning("⏸️ **Monitoring not started yet** - No checks performed")
    
    st.markdown("---")
    
    # Sidebar for admin controls
    with st.sidebar:
        st.header("⚙️ Admin Controls")
        
        # Admin authentication
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
            
            if st.button("🚀 Start Monitoring"):
                if start_monitoring():
                    st.success("Monitoring started!")
                    st.info("🔄 Using lightweight HTTP monitoring (Streamlit Cloud compatible)")
                else:
                    st.info("Monitoring is already running")
            
            if st.button("⏹️ Stop Monitoring"):
                stop_monitoring()
                st.success("Monitoring stopped!")
            
            if st.button("🚪 Logout"):
                st.session_state.admin_authenticated = False
                st.rerun()
        
        # Status display (visible to all users)
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
        
        # Admin-only subscriber management
        if is_admin_authenticated():
            st.markdown("---")
            st.subheader("👥 Subscriber Management")
            
            subscribers = monitor.load_subscribers()
            if subscribers:
                st.write(f"**{len(subscribers)} Active Subscribers:**")
                
                # Show subscriber list (admin only)
                with st.expander("View All Subscribers"):
                    df = pd.DataFrame(subscribers)
                    df['subscribed_at'] = pd.to_datetime(df['subscribed_at']).dt.strftime('%Y-%m-%d %H:%M')
                    st.dataframe(df[['name', 'email', 'subscribed_at']], use_container_width=True)
                
                # Admin unsubscribe
                with st.expander("Remove Subscriber"):
                    email_to_remove = st.selectbox("Select email to remove:", 
                                                 [s['email'] for s in subscribers])
                    if st.button("Remove Subscriber", type="secondary"):
                        if monitor.remove_subscriber(email_to_remove):
                            st.success(f"Removed {email_to_remove}")
                            st.rerun()
                        else:
                            st.error("Email not found")
            else:
                st.info("No subscribers yet")
        
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
        
        # Public unsubscribe section (self-service)
        st.header("🔕 Unsubscribe")
        st.markdown("*Only unsubscribe your own email address*")
        with st.form("unsubscribe_form"):
            unsub_email = st.text_input("Your email address", placeholder="email@example.com")
            unsub_submitted = st.form_submit_button("Unsubscribe")
            
            if unsub_submitted and unsub_email:
                if monitor.remove_subscriber(unsub_email):
                    st.success("Email unsubscribed successfully! **Stop Crying Your Heart Out** - you can always re-subscribe!")
                else:
                    st.warning("Email not found in our subscription list.")
    
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
        st.subheader("🎸 Supersonic Fans")
        
        # Show only subscriber count publicly (privacy-safe)
        subscriber_count = monitor.get_subscriber_count()
        if subscriber_count > 0:
            st.success(f"🌟 **{subscriber_count} Supersonic fans** are already subscribed!")
            st.markdown("*Join the crowd waiting for the comeback!*")
        else:
            st.info("**Be the first Supersonic fan to subscribe!** 🚀")
        
        # Privacy notice
        st.markdown("---")
        st.caption("🔒 **Privacy**: Your email is only used for ticket alerts and is kept secure.")

if __name__ == "__main__":
    main()
