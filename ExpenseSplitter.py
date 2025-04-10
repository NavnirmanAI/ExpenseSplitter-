import streamlit as st
import sqlite3
import os
import pandas as pd
from datetime import datetime


class Database:
    def __init__(self, db_file="expense_splitter.db"):
        """Initialize the database connection and create tables if they don't exist."""
        self.db_file = db_file
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Establish a connection to the SQLite database."""
        self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        
    def create_tables(self):
        """Create the necessary tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Create Person table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS person (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')
        
        # Create Expense table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS expense (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                paid_by INTEGER NOT NULL,
                FOREIGN KEY (paid_by) REFERENCES person(id)
            )
        ''')
        
        # Create ExpenseSplit table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS expense_split (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_id INTEGER NOT NULL,
                person_id INTEGER NOT NULL,
                share_amount REAL NOT NULL,
                FOREIGN KEY (expense_id) REFERENCES expense(id) ON DELETE CASCADE,
                FOREIGN KEY (person_id) REFERENCES person(id)
            )
        ''')
        
        self.conn.commit()
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()


class PersonManager:
    def __init__(self, db):
        """Initialize the PersonManager with a database connection."""
        self.db = db
    
    def add_person(self, name):
        """Add a new person to the database."""
        cursor = self.db.conn.cursor()
        try:
            cursor.execute('INSERT INTO person (name) VALUES (?)', (name,))
            self.db.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_all_persons(self):
        """Get all persons from the database."""
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT id, name FROM person ORDER BY name')
        return cursor.fetchall()
        
    def get_person_by_id(self, person_id):
        """Get a person by their ID."""
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT id, name FROM person WHERE id = ?', (person_id,))
        return cursor.fetchone()
    
    def update_person(self, person_id, name):
        """Update a person's name."""
        cursor = self.db.conn.cursor()
        try:
            cursor.execute('UPDATE person SET name = ? WHERE id = ?', (name, person_id))
            self.db.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def delete_person(self, person_id):
        """Delete a person by their ID."""
        cursor = self.db.conn.cursor()
        cursor.execute('DELETE FROM person WHERE id = ?', (person_id,))
        self.db.conn.commit()


class ExpenseManager:
    def __init__(self, db):
        """Initialize the ExpenseManager with a database connection."""
        self.db = db
    
    def add_expense(self, description, amount, date, paid_by, splits):
        """Add a new expense and its splits to the database."""
        cursor = self.db.conn.cursor()
        try:
            # Add the expense
            cursor.execute('''
                INSERT INTO expense (description, amount, date, paid_by)
                VALUES (?, ?, ?, ?)
            ''', (description, amount, date, paid_by))
            
            # Get the ID of the expense just added
            expense_id = cursor.lastrowid
            
            # Add the splits
            for person_id, share_amount in splits.items():
                cursor.execute('''
                    INSERT INTO expense_split (expense_id, person_id, share_amount)
                    VALUES (?, ?, ?)
                ''', (expense_id, person_id, share_amount))
            
            self.db.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return False
    
    def get_all_expenses(self):
        """Get all expenses with their payer information."""
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT e.id, e.description, e.amount, e.date, e.paid_by, p.name
            FROM expense e
            JOIN person p ON e.paid_by = p.id
            ORDER BY e.date DESC
        ''')
        return cursor.fetchall()
    
    def get_expense_by_id(self, expense_id):
        """Get an expense by its ID."""
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT e.id, e.description, e.amount, e.date, e.paid_by, p.name
            FROM expense e
            JOIN person p ON e.paid_by = p.id
            WHERE e.id = ?
        ''', (expense_id,))
        return cursor.fetchone()
    
    def get_expense_splits(self, expense_id):
        """Get all splits for a specific expense."""
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT es.id, es.expense_id, es.person_id, p.name, es.share_amount
            FROM expense_split es
            JOIN person p ON es.person_id = p.id
            WHERE es.expense_id = ?
        ''', (expense_id,))
        return cursor.fetchall()
    
    def update_expense(self, expense_id, description, amount, date, paid_by, splits):
        """Update an expense and its splits."""
        cursor = self.db.conn.cursor()
        try:
            # Update the expense
            cursor.execute('''
                UPDATE expense 
                SET description = ?, amount = ?, date = ?, paid_by = ?
                WHERE id = ?
            ''', (description, amount, date, paid_by, expense_id))
            
            # Delete existing splits
            cursor.execute('DELETE FROM expense_split WHERE expense_id = ?', (expense_id,))
            
            # Add the new splits
            for person_id, share_amount in splits.items():
                cursor.execute('''
                    INSERT INTO expense_split (expense_id, person_id, share_amount)
                    VALUES (?, ?, ?)
                ''', (expense_id, person_id, share_amount))
            
            self.db.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return False
    
    def delete_expense(self, expense_id):
        """Delete an expense and its splits."""
        cursor = self.db.conn.cursor()
        try:
            # Delete the expense (cascade will delete related splits)
            cursor.execute('DELETE FROM expense WHERE id = ?', (expense_id,))
            self.db.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return False
    
    def calculate_balances(self):
        """Calculate the current balances between all people."""
        cursor = self.db.conn.cursor()
        
        # Get all persons
        cursor.execute('SELECT id, name FROM person')
        persons = cursor.fetchall()
        
        balances = {}
        for person in persons:
            person_id, person_name = person
            balances[person_id] = {'name': person_name, 'balance': 0}
        
        # Calculate what each person paid
        cursor.execute('''
            SELECT paid_by, SUM(amount) as total_paid
            FROM expense
            GROUP BY paid_by
        ''')
        payments = cursor.fetchall()
        
        for paid_by, total_paid in payments:
            balances[paid_by]['balance'] += total_paid
        
        # Calculate what each person owes
        cursor.execute('''
            SELECT person_id, SUM(share_amount) as total_share
            FROM expense_split
            GROUP BY person_id
        ''')
        shares = cursor.fetchall()
        
        for person_id, total_share in shares:
            balances[person_id]['balance'] -= total_share
        
        return balances
    
    def get_settlement_plan(self):
        """Generate a plan to settle all debts."""
        balances = self.calculate_balances()
        
        # Extract people who owe money and people who are owed money
        debtors = []
        creditors = []
        
        for person_id, data in balances.items():
            if data['balance'] < 0:
                debtors.append((person_id, data['name'], abs(data['balance'])))
            elif data['balance'] > 0:
                creditors.append((person_id, data['name'], data['balance']))
        
        # Sort by amount (descending)
        debtors.sort(key=lambda x: x[2], reverse=True)
        creditors.sort(key=lambda x: x[2], reverse=True)
        
        # Generate settlement transactions
        transactions = []
        
        i, j = 0, 0
        while i < len(debtors) and j < len(creditors):
            debtor_id, debtor_name, debt = debtors[i]
            creditor_id, creditor_name, credit = creditors[j]
            
            if abs(debt - credit) < 0.01:  # Almost equal
                # Debtor pays creditor the full amount
                transactions.append((debtor_id, debtor_name, creditor_id, creditor_name, debt))
                i += 1
                j += 1
            elif debt < credit:
                # Debtor pays their full debt to creditor
                transactions.append((debtor_id, debtor_name, creditor_id, creditor_name, debt))
                creditors[j] = (creditor_id, creditor_name, credit - debt)
                i += 1
            else:  # debt > credit
                # Debtor pays part of their debt to creditor
                transactions.append((debtor_id, debtor_name, creditor_id, creditor_name, credit))
                debtors[i] = (debtor_id, debtor_name, debt - credit)
                j += 1
        
        return transactions


class ExpenseSplitterApp:
    def __init__(self):
        """Initialize the Expense Splitter App."""
        st.set_page_config(page_title="Expense Splitter App", page_icon="💰", layout="wide")
        
        # Initialize the database and managers
        self.db = Database()
        self.person_manager = PersonManager(self.db)
        self.expense_manager = ExpenseManager(self.db)
        
        # State initialization
        if 'page' not in st.session_state:
            st.session_state.page = 'dashboard'
        
        # Initialize session states for forms
        if 'edit_expense_id' not in st.session_state:
            st.session_state.edit_expense_id = None
        
        if 'edit_person_id' not in st.session_state:
            st.session_state.edit_person_id = None
    
    def run(self):
        """Run the Expense Splitter App."""
        st.title("💰 Expense Splitter App")
        
        # Sidebar navigation
        with st.sidebar:
            st.title("Navigation")
            if st.button("Dashboard", use_container_width=True):
                st.session_state.page = 'dashboard'
                st.session_state.edit_expense_id = None
                st.session_state.edit_person_id = None
            
            if st.button("Add Expense", use_container_width=True):
                st.session_state.page = 'add_expense'
                st.session_state.edit_expense_id = None
                st.session_state.edit_person_id = None
            
            if st.button("Manage People", use_container_width=True):
                st.session_state.page = 'manage_people'
                st.session_state.edit_expense_id = None
                st.session_state.edit_person_id = None
            
            if st.button("Settlement Plan", use_container_width=True):
                st.session_state.page = 'settlement'
                st.session_state.edit_expense_id = None
                st.session_state.edit_person_id = None
        
        # Page content
        if st.session_state.page == 'dashboard':
            self.show_dashboard()
        elif st.session_state.page == 'add_expense':
            if st.session_state.edit_expense_id is not None:
                self.show_edit_expense()
            else:
                self.show_add_expense()
        elif st.session_state.page == 'manage_people':
            self.show_manage_people()
        elif st.session_state.page == 'settlement':
            self.show_settlement()
    
    def show_dashboard(self):
        """Show the dashboard with expense list and balances."""
        st.header("Dashboard")
        
        # Display all expenses
        expenses = self.expense_manager.get_all_expenses()
        if expenses:
            expense_data = []
            for exp in expenses:
                exp_id, description, amount, date, paid_by, paid_by_name = exp
                expense_data.append({
                    "ID": exp_id,
                    "Description": description,
                    "Amount": f"${amount:.2f}",
                    "Date": date,
                    "Paid By": paid_by_name
                })
            
            df = pd.DataFrame(expense_data)
            st.subheader("Recent Expenses")
            st.dataframe(df, use_container_width=True)
            
            # Add action buttons for each expense
            col1, col2 = st.columns(2)
            with col1:
                selected_expense = st.selectbox("Select an expense to modify:", 
                                             options=[e[0] for e in expenses],
                                             format_func=lambda x: next((e[1] for e in expenses if e[0] == x), ""))
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("View/Edit Expense", use_container_width=True):
                    st.session_state.edit_expense_id = selected_expense
                    st.session_state.page = 'add_expense'
                    st.rerun()
            with col2:
                if st.button("Delete Expense", use_container_width=True):
                    if self.expense_manager.delete_expense(selected_expense):
                        st.success("Expense deleted successfully!")
                        st.rerun()
                    else:
                        st.error("Failed to delete expense.")
        else:
            st.info("No expenses found. Add some expenses to get started!")
        
        # Display current balances
        balances = self.expense_manager.calculate_balances()
        if balances:
            st.subheader("Current Balances")
            balance_data = []
            for person_id, data in balances.items():
                balance_data.append({
                    "Person": data['name'],
                    "Balance": f"${data['balance']:.2f}",
                    "Status": "Owed money" if data['balance'] > 0 else "Owes money" if data['balance'] < 0 else "Settled"
                })
            
            balance_df = pd.DataFrame(balance_data)
            st.dataframe(balance_df, use_container_width=True)
        
    def show_add_expense(self):
        """Show the add expense form."""
        st.header("Add New Expense")
        
        # Get all persons
        persons = self.person_manager.get_all_persons()
        if not persons:
            st.warning("You need to add people before adding expenses.")
            return
        
        # Expense details form
        with st.form(key="add_expense_form"):
            description = st.text_input("Description", max_chars=100)
            amount = st.number_input("Amount ($)", min_value=0.01, value=10.00, step=0.01)
            date = st.date_input("Date", datetime.now())
            
            # Who paid
            paid_by = st.selectbox(
                "Who paid?",
                options=[p[0] for p in persons],
                format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
            )
            
            st.subheader("Split the expense")
            
            # Options for splitting
            split_method = st.radio(
                "How do you want to split the expense?",
                options=["Equally", "Custom amounts", "Custom percentages"]
            )
            
            # Container for splits
            split_container = st.container()
            
            with split_container:
                splits = {}
                
                if split_method == "Equally":
                    # Select who's involved in the split
                    involved_persons = st.multiselect(
                        "Who's involved in this expense?",
                        options=[p[0] for p in persons],
                        default=[p[0] for p in persons],
                        format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
                    )
                    
                    if involved_persons:
                        equal_share = amount / len(involved_persons)
                        for person_id in involved_persons:
                            splits[person_id] = equal_share
                        
                        # Show the splits
                        st.write("Each person pays: ${:.2f}".format(equal_share))
                    
                elif split_method == "Custom amounts":
                    st.write("Enter the amount each person should pay:")
                    total_assigned = 0
                    
                    # For each person, create an input for their share
                    for person_id, person_name in persons:
                        share = st.number_input(
                            f"{person_name}'s share ($)",
                            min_value=0.0,
                            max_value=float(amount),
                            value=0.0,
                            step=0.01,
                            key=f"amount_{person_id}"
                        )
                        if share > 0:
                            splits[person_id] = share
                            total_assigned += share
                    
                    # Show the total assigned and remaining
                    st.write(f"Total assigned: ${total_assigned:.2f}")
                    remaining = amount - total_assigned
                    if abs(remaining) > 0.01:  # More than 1 cent difference
                        st.warning(f"Remaining to assign: ${remaining:.2f}")
                    
                elif split_method == "Custom percentages":
                    st.write("Enter the percentage each person should pay:")
                    total_percentage = 0
                    
                    # For each person, create an input for their percentage
                    for person_id, person_name in persons:
                        percentage = st.number_input(
                            f"{person_name}'s percentage",
                            min_value=0.0,
                            max_value=100.0,
                            value=0.0,
                            step=1.0,
                            key=f"percentage_{person_id}"
                        )
                        if percentage > 0:
                            share = amount * (percentage / 100)
                            splits[person_id] = share
                            total_percentage += percentage
                    
                    # Show the total percentage and shares
                    st.write(f"Total percentage: {total_percentage:.1f}%")
                    if abs(total_percentage - 100) > 0.1:  # More than 0.1% difference
                        st.warning(f"Total should be 100% (currently {total_percentage:.1f}%)")
                    
                    # Show the calculated amounts
                    if splits:
                        st.write("Calculated amounts:")
                        for person_id, share in splits.items():
                            person_name = next((p[1] for p in persons if p[0] == person_id), "")
                            st.write(f"{person_name}: ${share:.2f}")
            
            submit_button = st.form_submit_button("Add Expense")
            
            if submit_button:
                # Validate the form
                if not description:
                    st.error("Please enter a description.")
                elif amount <= 0:
                    st.error("Amount must be greater than zero.")
                elif not splits:
                    st.error("Please split the expense among at least one person.")
                elif split_method in ["Custom amounts", "Custom percentages"] and abs(sum(splits.values()) - amount) > 0.01:
                    st.error("The total split amount must equal the expense amount.")
                else:
                    # Add the expense
                    date_str = date.strftime("%Y-%m-%d")
                    if self.expense_manager.add_expense(description, amount, date_str, paid_by, splits):
                        st.success("Expense added successfully!")
                        # Reset form
                        st.session_state.page = 'dashboard'
                        st.rerun()
                    else:
                        st.error("Failed to add expense.")
    
    def show_edit_expense(self):
        """Show the edit expense form."""
        st.header("Edit Expense")
        
        # Get expense details
        expense = self.expense_manager.get_expense_by_id(st.session_state.edit_expense_id)
        if not expense:
            st.error("Expense not found.")
            return
        
        expense_id, description, amount, date_str, paid_by, paid_by_name = expense
        
        # Get splits
        splits = self.expense_manager.get_expense_splits(expense_id)
        
        # Get all persons
        persons = self.person_manager.get_all_persons()
        
        # Convert existing splits to dictionary
        existing_splits = {}
        for _, _, person_id, _, share in splits:
            existing_splits[person_id] = share
        
        # Expense details form
        with st.form(key="edit_expense_form"):
            new_description = st.text_input("Description", value=description, max_chars=100)
            new_amount = st.number_input("Amount ($)", min_value=0.01, value=float(amount), step=0.01)
            
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                date_obj = datetime.now().date()
            
            new_date = st.date_input("Date", date_obj)
            
            # Who paid
            new_paid_by = st.selectbox(
                "Who paid?",
                options=[p[0] for p in persons],
                index=[p[0] for p in persons].index(paid_by) if paid_by in [p[0] for p in persons] else 0,
                format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
            )
            
            st.subheader("Split the expense")
            
            # Determine the current split method
            equal_split = True
            custom_percentages = True
            
            # Check if all shares are equal
            if existing_splits:
                share_values = list(existing_splits.values())
                equal_split = all(abs(share - share_values[0]) < 0.01 for share in share_values)
            
            # Check if shares represent percentages
            if existing_splits and abs(sum(existing_splits.values()) - amount) < 0.01:
                for share in existing_splits.values():
                    if abs((share / amount) * 100 - round((share / amount) * 100)) > 0.1:
                        custom_percentages = False
                        break
            else:
                custom_percentages = False
            
            # Default split method based on existing data
            default_method = "Equally" if equal_split else "Custom percentages" if custom_percentages else "Custom amounts"
            
            # Options for splitting
            split_method = st.radio(
                "How do you want to split the expense?",
                options=["Equally", "Custom amounts", "Custom percentages"],
                index=["Equally", "Custom amounts", "Custom percentages"].index(default_method)
            )
            
            # Container for splits
            split_container = st.container()
            
            with split_container:
                new_splits = {}
                
                if split_method == "Equally":
                    # Select who's involved in the split
                    involved_persons = st.multiselect(
                        "Who's involved in this expense?",
                        options=[p[0] for p in persons],
                        default=[p[0] for p in persons if p[0] in existing_splits],
                        format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
                    )
                    
                    if involved_persons:
                        equal_share = new_amount / len(involved_persons)
                        for person_id in involved_persons:
                            new_splits[person_id] = equal_share
                        
                        # Show the splits
                        st.write("Each person pays: ${:.2f}".format(equal_share))
                    
                elif split_method == "Custom amounts":
                    st.write("Enter the amount each person should pay:")
                    total_assigned = 0
                    
                    # For each person, create an input for their share
                    for person_id, person_name in persons:
                        default_share = existing_splits.get(person_id, 0.0)
                        share = st.number_input(
                            f"{person_name}'s share ($)",
                            min_value=0.0,
                            max_value=float(new_amount),
                            value=float(default_share),
                            step=0.01,
                            key=f"edit_amount_{person_id}"
                        )
                        if share > 0:
                            new_splits[person_id] = share
                            total_assigned += share
                    
                    # Show the total assigned and remaining
                    st.write(f"Total assigned: ${total_assigned:.2f}")
                    remaining = new_amount - total_assigned
                    if abs(remaining) > 0.01:  # More than 1 cent difference
                        st.warning(f"Remaining to assign: ${remaining:.2f}")
                    
                elif split_method == "Custom percentages":
                    st.write("Enter the percentage each person should pay:")
                    total_percentage = 0
                    
                    # For each person, create an input for their percentage
                    for person_id, person_name in persons:
                        default_percentage = (existing_splits.get(person_id, 0.0) / amount * 100) if amount > 0 else 0.0
                        percentage = st.number_input(
                            f"{person_name}'s percentage",
                            min_value=0.0,
                            max_value=100.0,
                            value=float(default_percentage),
                            step=1.0,
                            key=f"edit_percentage_{person_id}"
                        )
                        if percentage > 0:
                            share = new_amount * (percentage / 100)
                            new_splits[person_id] = share
                            total_percentage += percentage
                    
                    # Show the total percentage and shares
                    st.write(f"Total percentage: {total_percentage:.1f}%")
                    if abs(total_percentage - 100) > 0.1:  # More than 0.1% difference
                        st.warning(f"Total should be 100% (currently {total_percentage:.1f}%)")
                    
                    # Show the calculated amounts
                    if new_splits:
                        st.write("Calculated amounts:")
                        for person_id, share in new_splits.items():
                            person_name = next((p[1] for p in persons if p[0] == person_id), "")
                            st.write(f"{person_name}: ${share:.2f}")
            
            submit_button = st.form_submit_button("Update Expense")
            
            if submit_button:
                # Validate the form
                if not new_description:
                    st.error("Please enter a description.")
                elif new_amount <= 0:
                    st.error("Amount must be greater than zero.")
                elif not new_splits:
                    st.error("Please split the expense among at least one person.")
                elif split_method in ["Custom amounts", "Custom percentages"] and abs(sum(new_splits.values()) - new_amount) > 0.01:
                    st.error("The total split amount must equal the expense amount.")
                else:
                    # Update the expense
                    date_str = new_date.strftime("%Y-%m-%d")
                    if self.expense_manager.update_expense(expense_id, new_description, new_amount, date_str, new_paid_by, new_splits):
                        st.success("Expense updated successfully!")
                        # Reset form and go back to dashboard
                        st.session_state.edit_expense_id = None
                        st.session_state.page = 'dashboard'
                        st.rerun()
                    else:
                        st.error("Failed to update expense.")
        
        # Add a button to cancel editing
        if st.button("Cancel", use_container_width=True):
            st.session_state.edit_expense_id = None
            st.session_state.page = 'dashboard'
            st.rerun()
    
    def show_manage_people(self):
        """Show the manage people page."""
        st.header("Manage People")
        
        # Add person form
        with st.form(key="add_person_form", clear_on_submit=True):
            st.subheader("Add New Person")
            new_person_name = st.text_input("Name", key="new_person_name", max_chars=50)
            add_button = st.form_submit_button("Add Person")
            
            if add_button:
                if new_person_name:
                    if self.person_manager.add_person(new_person_name):
                        st.success(f"Added {new_person_name} successfully!")
                        st.rerun()
                    else:
                        st.error(f"Person with name '{new_person_name}' already exists.")
                else:
                    st.error("Please enter a name.")
        
        # List of existing people
        st.subheader("Existing People")
        persons = self.person_manager.get_all_persons()
        
        if persons:
            person_data = []
            for person_id, name in persons:
                person_data.append({
                    "ID": person_id,
                    "Name": name
                })
            
            df = pd.DataFrame(person_data)
            st.dataframe(df, use_container_width=True)
            
            # Edit/Delete person
            st.subheader("Edit or Delete Person")
            selected_person = st.selectbox(
                "Select a person:",
                options=[p[0] for p in persons],
                format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
            )
            
            col1, col2