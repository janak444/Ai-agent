import json
import os

class Transaction:
    def __init__(self, amount, category, description):
        self.amount = amount
        self.category = category
        self.description = description

class FinanceTracker:
    def __init__(self, filename='finance.json'):
        self.filename = filename
        self.transactions = self.load_transactions()

    def add_transaction(self, amount, category, description):
        self.transactions.append(Transaction(amount, category, description))
        self.save_transactions()

    def add_income(self, amount, category, description):
        self.transactions.append(Transaction(amount, category, description))
        self.save_transactions()

    def add_expense(self, amount, category, description):
        self.transactions.append(Transaction(-amount, category, description))
        self.save_transactions()

    def categorize(self, category):
        return [t for t in self.transactions if t.category == category]

    def generate_summary(self):
        total_balance = sum(t.amount for t in self.transactions)
        spending_per_category = {}
        for t in self.transactions:
            category = t.category
            if category in spending_per_category:
                spending_per_category[category] += abs(t.amount)
            else:
                spending_per_category[category] = abs(t.amount)
        return total_balance, spending_per_category

    def save_transactions(self):
        with open(self.filename, 'w') as f:
            json.dump(self.transactions, f)

    def load_transactions(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r') as f:
                return json.load(f)
        else:
            return []

def main():
    tracker = FinanceTracker()

    while True:
        print("1. Add transaction")
        print("2. Add income")
        print("3. Add expense")
        print("4. Generate summary")
        print("5. Quit")
        choice = input("Choose an option: ")
        if choice == '1':
            amount = float(input("Enter amount: "))
            category = input("Enter category: ")
            description = input("Enter description: ")
            tracker.add_transaction(amount, category, description)
        elif choice == '2':
            amount = float(input("Enter amount: "))
            category = input("Enter category: ")
            description = input("Enter description: ")
            tracker.add_income(amount, category, description)
        elif choice == '3':
            amount = float(input("Enter amount: "))
            category = input("Enter category: ")
            description = input("Enter description: ")
            tracker.add_expense(amount, category, description)
        elif choice == '4':
            total_balance, spending_per_category = tracker.generate_summary()
            print(f"Total balance: {total_balance}")
            for category, amount in spending_per_category.items():
                print(f"{category}: {amount}")
        elif choice == '5':
            break
        else:
            print("Invalid choice. Please choose a valid option.")

if __name__ == "__main__":
    main()