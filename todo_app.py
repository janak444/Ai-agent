class TodoList:
    def __init__(self):
        self.tasks = {}

    def add_task(self, task_name, task_description):
        self.tasks[task_name] = task_description
        print(f"Task '{task_name}' added successfully.")

    def delete_task(self, task_name):
        if task_name in self.tasks:
            del self.tasks[task_name]
            print(f"Task '{task_name}' deleted successfully.")
        else:
            print(f"Task '{task_name}' not found.")

    def edit_task(self, task_name, new_description):
        if task_name in self.tasks:
            self.tasks[task_name] = new_description
            print(f"Task '{task_name}' edited successfully.")
        else:
            print(f"Task '{task_name}' not found.")

    def view_tasks(self):
        if not self.tasks:
            print("No tasks available.")
        else:
            print("Available Tasks:")
            for task, description in self.tasks.items():
                print(f"{task} - {description}")


def main():
    todo_list = TodoList()

    while True:
        print("\nTodo List Manager")
        print("1. Add Task")
        print("2. Delete Task")
        print("3. Edit Task")
        print("4. View Tasks")
        print("5. Quit")

        choice = input("Enter your choice: ")

        if choice == "1":
            task_name = input("Enter task name: ")
            task_description = input("Enter task description: ")
            todo_list.add_task(task_name, task_description)
        elif choice == "2":
            task_name = input("Enter task name: ")
            todo_list.delete_task(task_name)
        elif choice == "3":
            task_name = input("Enter task name: ")
            new_description = input("Enter new task description: ")
            todo_list.edit_task(task_name, new_description)
        elif choice == "4":
            todo_list.view_tasks()
        elif choice == "5":
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please choose a valid option.")


if __name__ == "__main__":
    main()