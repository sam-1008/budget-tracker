# pyrefly: ignore [missing-import]
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
# pyrefly: ignore [missing-import]
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import os
import csv
import io
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import letter
import smtplib
from email.mime.text import MIMEText

# Email Configurations
EMAIL_ADDRESS = "tanafranca.ss@shc.edu.ph"
EMAIL_PASSWORD = "srqe lyut smeu rtox"

# Sends an automated email notification using SMTP
def send_email_notif(receiver, subject, message):
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = receiver
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print("Email error:", e)

app = Flask(__name__)
app.secret_key = 'privateKey'

DATA_FILE = 'storage.json'
USERS_FILE = 'users.json'

# Reads user credentials and profiles from users.json
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as file:
            try:
                return json.load(file)
            except:
                return []
    return []

# Persists the current list of users to users.json
def save_users(users):
    with open(USERS_FILE, 'w') as file:
        json.dump(users, file, indent=4)

# Retrieves a specific user's profile data by their email address
def get_user_data(email):
    users = load_users()
    for user in users:
        if user['email'] == email:
            return user
    return None

# Global dictionary to hold all users' categories
# Structure: { "email": [BudgetCategory, ...] }
all_user_data = {}

# Loads all user categories and transactions from storage.json into memory
def load_all_categories():
    global all_user_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as file:
                content = file.read()
                if not content:
                    all_user_data = {}
                    return
                raw_data = json.loads(content)
                # raw_data should be { "email": [ {category_dict}, ... ] }
                # But handle legacy format (list) by assigning to a default if needed
                if isinstance(raw_data, list):
                    # Migration: Assign old data to a dummy or clear it
                    all_user_data = {} 
                else:
                    for email, cat_list in raw_data.items():
                        all_user_data[email] = [BudgetCategory.from_dict(cat) for cat in cat_list]
        except (json.JSONDecodeError, ValueError):
            all_user_data = {}

# Persists all category and transaction data back to storage.json
def save_all_categories():
    with open(DATA_FILE, 'w') as file:
        serialized = {email: [cat.to_dict() for cat in cat_list] for email, cat_list in all_user_data.items()}
        json.dump(serialized, file, indent=4)

# Helper to get the category list for the currently logged-in user
def get_current_user_categories():
    email = session.get('user')
    if not email:
        return []
    return all_user_data.get(email, [])

# Helper to update and save the category list for the current user
def set_current_user_categories(categories_list):
    email = session.get('user')
    if email:
        all_user_data[email] = categories_list
        save_all_categories()

# Core class representing a budget category with balance and transaction history
class BudgetCategory:
    def __init__(self, name, balance):
        self.name = name
        self.balance = balance
        self.transaction = []

    # Helper to generate a standardized ISO timestamp for logs
    def _get_timestamp(self):
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    
    # Increases category balance and logs the deposit
    def add_funds(self, amount):
        if amount > 0:
            self.balance += amount
            self.transaction.append(f"[{self._get_timestamp()}] | Added Funds: ₱{amount}")
            return True
        return False
    
    # Deducts an expense from the balance and logs the transaction details
    def log_expense(self, amount, description="Expense"):
        if 0 < amount <= self.balance:
            self.balance -= amount
            self.transaction.append(f"[{self._get_timestamp()}] | Spent: ₱{amount} ({description})")
            return True
        return False
    
    # Transfers funds directly between two categories
    def reallocate(self, receiver_category, amount):
        if amount <= 0 or amount > self.balance:
            return False

        time_str = self._get_timestamp()
        self.balance -= amount
        receiver_category.balance += amount
        
        self.transaction.append(f"[{time_str}] | Reallocated ₱{amount} to {receiver_category.name}")
        receiver_category.transaction.append(f"[{time_str}] | Received ₱{amount} from {self.name}")
        return True
    
    # Converts object data to a dictionary for JSON serialization
    def to_dict(self):
        return {
            'name': self.name,
            'balance': self.balance,
            'transaction': self.transaction
        }
    
    # Reconstructs a BudgetCategory object from a dictionary
    @staticmethod
    def from_dict(data):
        cat = BudgetCategory(data['name'], data['balance'])
        cat.transaction = data.get('transaction', [])
        return cat

# Utility to find a specific category by name within the current user's data
def find_category(name):
    categories = get_current_user_categories()
    for cat in categories:
        if cat.name == name:
            return cat
    return None

load_all_categories()

## ROUTES
# Landing page route (redirects to dashboard if already logged in)
@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# Handles user authentication and session creation
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        pin = request.form['pin']
        
        user = get_user_data(email)
        if user and check_password_hash(user['pin_hash'], str(pin)):
            session['user'] = email
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or PIN. Please try again.", "error")
        return redirect(url_for('login'))

    return render_template('login.html')

# Manages new user registration, password hashing, and welcome emails
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        username = request.form['username']
        email = request.form['email']
        pin = request.form['pin']
        
        if not (pin.isdigit() and len(pin) == 4):
            flash("PIN must be exactly 4 digits.", "error")
            return redirect(url_for('register'))
            
        users = load_users()
        if any(u['email'] == email for u in users):
            flash("Email already registered.", "error")
            return redirect(url_for('register'))
        
        if any(u['username'] == username for u in users):
            flash("Username already taken.", "error")
            return redirect(url_for('register'))

        new_user = {
            'full_name': full_name,
            'username': username,
            'email': email,
            'pin_hash': generate_password_hash(pin)
        }
        users.append(new_user)
        save_users(users)
        
        # Initialize empty category list for user
        all_user_data[email] = []
        save_all_categories()
        
        # Send notification email
        email_subject = "Welcome to FinTrack - Account Created"
        email_message = (
            f"Hello {full_name},\n\n"
            f"Your FinTrack account has been successfully created!\n"
            f"Username: {username}\n"
            f"Email: {email}\n\n"
            f"You can now start managing your budget and tracking your expenses.\n\n"
            f"Happy Budgeting!\nThe FinTrack Team"
        )
        send_email_notif(email, email_subject, email_message)
        
        flash("Account created successfully! A notification email has been sent.", "success")
        return redirect(url_for('login'))
        
    return render_template('register.html')

# Creates a new budget category for the logged-in user
@app.route('/create_category', methods=['POST'])
def create_category():
    if 'user' not in session:
        return redirect(url_for('login'))

    name = request.form['name']
    balance = float(request.form['balance'])
    
    categories = get_current_user_categories()
    if find_category(name):
        flash("Category already exists!", "error")
        return redirect(url_for('dashboard'))
    
    categories.append(BudgetCategory(name, balance))
    set_current_user_categories(categories)
    flash(f"Category '{name}' created successfully!", "success")
    return redirect(url_for('dashboard'))

# Updates an existing category's name and balance
@app.route('/edit_category/<name>', methods=['POST'])
def edit_category(name):
    if 'user' not in session:
        return redirect(url_for('login'))
    
    category = find_category(name)
    if not category:
        flash("Category not found.", "error")
        return redirect(url_for('dashboard'))

    new_name = request.form['name']
    new_balance = float(request.form['balance'])
    
    if new_name != name and find_category(new_name):
        flash("Category name already exists!", "error")
        return redirect(url_for('dashboard'))
    
    category.name = new_name
    category.balance = new_balance
    save_all_categories()
    flash(f"Category '{new_name}' updated successfully!", "success")
    return redirect(url_for('dashboard'))

# Removes a category from the user's budget
@app.route('/delete_category/<name>')
def delete_category(name):
    if 'user' not in session:
        return redirect(url_for('login'))
    
    category = find_category(name)
    if category:
        categories = get_current_user_categories()
        categories = [cat for cat in categories if cat.name != name]
        set_current_user_categories(categories)
        flash(f"Category '{name}' deleted successfully!", "success")
    else:
        flash("Category not found.", "error")
    
    return redirect(url_for('dashboard'))

# Main dashboard: calculates financial summaries, filters history, and renders UI
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    time_filter = request.args.get('filter', 'all')
    now = datetime.now()
    
    categories = get_current_user_categories()
    total_balance = sum(cat.balance for cat in categories)
    
    total_income = 0.0
    total_spent = 0.0
    
    def is_within_filter(date_str, filter_type):
        if filter_type == 'all': return True
        try:
            tx_date = datetime.fromisoformat(date_str)
            delta = now - tx_date
            if filter_type == '1d': return delta.days <= 1
            if filter_type == '3d': return delta.days <= 3
            if filter_type == '7d': return delta.days <= 7
            if filter_type == '30d': return delta.days <= 30
            if filter_type == '1y': return delta.days <= 365
        except: pass
        return True

    recent_txs = []
    all_time_spent = 0.0
    for cat in categories:
        for tx in cat.transaction:
            if ']' in tx:
                parts = tx.split('] | ')
                if len(parts) > 1:
                    date_str = parts[0].replace('[', '')
                    detail = parts[1]
                    is_reallocated = 'Reallocated' in detail
                    is_received = 'Received' in detail and 'from' in detail
                    is_income = 'Added Funds:' in detail or 'Deposited:' in detail or is_received
                    
                    # For summary/utilization, we only count external spending as 'spent'
                    # Internal reallocations don't reduce your total net worth
                    is_actual_expense = ('Spent:' in detail or 'Transferred' in detail) and not is_reallocated and not is_received
                    
                    # For list styling, we keep the is_spent flag to maintain the red/orange/green logic 
                    # but we'll prioritize tx_type for the icon
                    is_spent_for_list = is_actual_expense or (is_reallocated and 'to' in detail)
                    
                    tx_type = 'reallocated' if is_reallocated or is_received else 'income' if is_income else 'spent'

                    # Track all time spent for the income baseline
                    if is_actual_expense:
                        try:
                            amt = float(detail.split('₱')[1].split(' ')[0])
                            all_time_spent += amt
                        except: pass

                    recent_txs.append({
                        'date': date_str,
                        'detail': detail,
                        'category': cat.name,
                        'is_spent': is_spent_for_list,
                        'type': tx_type
                    })
                    
                    if not is_within_filter(date_str, time_filter):
                        continue
                        
                    if is_actual_expense:
                        try:
                            amt = float(detail.split('₱')[1].split(' ')[0])
                            total_spent += amt
                        except: pass
                    elif is_income and not is_received: # Only count external deposits as income
                        try:
                            amt = float(detail.split('₱')[1].split(' ')[0])
                            total_income += amt
                        except: pass
                        
    # The 'Total Income' used for the progress bar baseline should be the 
    # Total Lifetime Funds (Current Balance + All-Time Expenses).
    # This provides a consistent 0-100% scale representing overall budget health.
    summary_income = total_balance + all_time_spent
    
    # If the filter is 'all', we show the lifetime stats.
    # If filtered, we show income/spent for that period but keep the progress bar stable.
    if time_filter == 'all':
        total_income = summary_income
        
    recent_txs.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = recent_txs[:5]
        
    return render_template('dashboard.html', 
                         categories=categories, 
                         total_balance=total_balance, 
                         total_income=total_income, 
                         total_spent=total_spent, 
                         summary_income=summary_income,
                         current_filter=time_filter, 
                         recent_transactions=recent_transactions)

# Handles adding funds or logging expenses with low-budget email alerts
@app.route('/add_transaction', methods=['GET', 'POST'])
def add_transaction():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        action = request.form['action']
        cat_name = request.form['category']
        amount = float(request.form['amount'])
        
        category = find_category(cat_name)
        
        if not category:
            flash("Category not found.", "error")
            return redirect(url_for('add_transaction'))

        if action == 'add_funds':
            if category.add_funds(amount):
                flash(f"Successfully added ₱{amount} to {category.name}", "success")
            else:
                flash("Failed to add funds. Invalid amount.", "error")

        elif action == 'log_expense':
            description = request.form.get('description', 'Expense')
            if category.log_expense(amount, description):
                if category.balance <= 0:
                    send_email_notif( 
                         EMAIL_ADDRESS,
                         f"Alert Notification: {category.name} is EMPTY",
                         f"Alert!\n\nYou just spent ₱{amount} on {description}.\n"
                         f"Your remaining budget for {category.name} is exactly ₱0.\n\n"
                         f"You have no funds left in this category!")
                    flash(f"ALERT: {category.name} is EMPTY! You have ₱0 remaining.", "error")
                elif category.balance < 100:
                    send_email_notif( 
                         EMAIL_ADDRESS,
                         f"Warning Notification: {category.name} Budget Low",
                         f"Warning!\n\nYou just spent ₱{amount} on {description}.\n"
                         f"Your remaining budget for {category.name} is critically low: ₱{category.balance}.\n\n"
                         f"Please review your expenses carefully.")
                    flash(f"WARNING: {category.name} budget is critically low (₱{category.balance}).", "error")
                elif category.balance < 500:
                    send_email_notif( 
                         EMAIL_ADDRESS,
                         f"Reminder Notification: {category.name} Budget Update",
                         f"Reminder.\n\nYou just spent ₱{amount} on {description}.\n"
                         f"Your remaining budget for {category.name} has dropped to ₱{category.balance}.\n\n"
                         f"Keep an eye on your spending.")
                    flash(f"REMINDER: {category.name} budget dropped to ₱{category.balance}.", "warning")
                
                flash(f"Successfully logged ₱{amount} expense for {category.name}", "success")
            else:
                flash("Expense failed. Insufficient budget or invalid amount.", "error")
        
        save_all_categories()
        return redirect(url_for('dashboard'))
        
    categories = get_current_user_categories()
    return render_template('add_transaction.html', categories=categories)

# Renders the full paginated transaction history for the user
@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    categories = get_current_user_categories()
    all_transactions = []
    for cat in categories:
        for tx in cat.transaction:
            if ']' in tx:
                parts = tx.split('] | ')
                if len(parts) == 2:
                    date_part = parts[0].replace('[', '')
                    detail_part = parts[1]
                    
                    is_reallocated = 'Reallocated' in detail_part
                    is_received = 'Received' in detail_part and 'from' in detail_part
                    is_income = 'Added Funds:' in detail_part or 'Deposited:' in detail_part or is_received
                    is_actual_expense = ('Spent:' in detail_part or 'Transferred' in detail_part) and not is_reallocated and not is_received
                    is_spent_for_list = is_actual_expense or (is_reallocated and 'to' in detail_part)
                    
                    tx_type = 'reallocated' if is_reallocated or is_received else 'income' if is_income else 'spent'

                    all_transactions.append({
                        'date': date_part,
                        'detail': detail_part,
                        'category': cat.name,
                        'is_spent': is_spent_for_list,
                        'type': tx_type
                    })
                    
    all_transactions.sort(key=lambda x: x['date'], reverse=True)
    
    total_tx = len(all_transactions)
    total_pages = max(1, (total_tx + per_page - 1) // per_page)
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_tx = all_transactions[start_idx:end_idx]
    
    return render_template('history.html', transactions=paginated_tx, page=page, total_pages=total_pages)

# Deletes all transaction logs across all user categories
@app.route('/clear_history')
def clear_history():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    categories = get_current_user_categories()
    for cat in categories:
        cat.transaction = []
        
    save_all_categories()
    flash("Activity history cleared successfully.", "success")
    return redirect(url_for('history'))

# Resets all category balances to zero and clears all history
@app.route('/reset_all_data')
def reset_all_data():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    categories = get_current_user_categories()
    for cat in categories:
        cat.balance = 0.0
        cat.transaction = []
        
    save_all_categories()
    flash("All account data has been reset successfully.", "success")
    return redirect(url_for('dashboard'))

# Interface for moving funds between two categories
@app.route('/reallocate', methods=['GET', 'POST'])
def reallocate():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        source_name = request.form['source']
        receiver_name = request.form['receiver']
        amount = float(request.form['amount'])
        
        source = find_category(source_name)
        receiver = find_category(receiver_name)

        if source and receiver and source.reallocate(receiver, amount):
            send_email_notif(
                 EMAIL_ADDRESS,
                 f"Reallocation Alert: Funds Moved",
                 f"Reallocation Successful.\n\n"
                 f"You moved ₱{amount} from {source_name} to {receiver_name}.\n"
                 f"Remaining balance for {source_name}: ₱{source.balance}\n"
                 f"New balance for {receiver_name}: ₱{receiver.balance}\n"
            )
            save_all_categories()
            flash(f"Successfully moved ₱{amount} from {source_name} to {receiver_name}", "success")
            return redirect(url_for('dashboard'))
        flash("Reallocation Failed. Check source balance.", "error")
        return redirect(url_for('reallocate'))
    
    categories = get_current_user_categories()
    return render_template('reallocate.html', categories=categories)

# Clears the user session and redirects to login
@app.route('/logout')
def logout():
    if 'user' not in session:
        return redirect(url_for('login'))
    session.pop('user', None)
    flash("Logged out successfully.", "success")
    return redirect(url_for('login'))

# Generates and serves a CSV file of all user transactions
@app.route('/download_report')
def download_report():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    output = io.StringIO()
    output.write('\ufeff')  # Add UTF-8 BOM for Excel compatibility
    writer = csv.writer(output)

    writer.writerow(['Category', 'Date/Time', 'Transaction Details'])

    categories = get_current_user_categories()
    for cat in categories:
        for tx in cat.transaction:
            if ']' in tx:
                parts = tx.split(']', 1)
                date = parts[0].replace('[', '')
                details = parts[1].strip()
                writer.writerow([cat.name, date, details])
            else:
                writer.writerow([cat.name, 'N/A', tx])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename="expense_report.csv"'
        }
    )

# Generates and serves a PDF summary of all user transactions
@app.route('/download_pdf_report')
def download_pdf_report():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    buffer = io.BytesIO()
    data = [['Category', 'Date/Time', 'Transaction Details']]

    categories = get_current_user_categories()
    for cat in categories:
        for tx in cat.transaction:
            if ']' in tx:
                parts = tx.split(']', 1)
                date = parts[0].replace('[', '')
                # ReportLab's default font doesn't support '₱', replace with 'PHP '
                details = parts[1].strip().replace('₱', 'PHP ')
                data.append([cat.name.replace('₱', 'PHP '), date, details])
    
    pdf = SimpleDocTemplate(buffer, pagesize=letter)
    table = Table(data)
    pdf.build([table])

    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': 'attachment; filename="expense_report.pdf"'
        }
    )

if __name__ == '__main__':
    app.run(debug=True, port=5001)
