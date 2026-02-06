"""
Script to create an admin account
Usage: python create_admin.py
"""
import os
import sys
from werkzeug.security import generate_password_hash

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(__file__))

from aws_client import AwsClient

def create_admin():
    aws = AwsClient()
    
    print("=" * 50)
    print("Admin Account Creation")
    print("=" * 50)
    
    # Check if default admin should be created
    create_default = input("Create default admin? (y/n): ").strip().lower()
    
    if create_default == 'y':
        email = "admin@virtualcareercounselor.com"
        password = "admin123"
        name = "System Administrator"
        print(f"\nCreating default admin with:")
        print(f"Email: {email}")
        print(f"Password: {password}")
    else:
        email = input("Enter admin email: ").strip()
        if not email:
            print("Error: Email is required")
            return
        
        password = input("Enter admin password: ").strip()
        if not password:
            print("Error: Password is required")
            return
        
        name = input("Enter admin name (optional): ").strip()
    
    # Check if admin already exists
    existing = aws.get_admin_by_email(email)
    if existing:
        print(f"\nAdmin with email {email} already exists!")
        overwrite = input("Do you want to update the password? (y/n): ").strip().lower()
        if overwrite == 'y':
            existing['passwordHash'] = generate_password_hash(password)
            if name:
                existing['name'] = name
            store = aws._read_store()
            admins = store.get('admins', [])
            for i, a in enumerate(admins):
                if a.get('email') == email:
                    admins[i] = existing
                    break
            store['admins'] = admins
            aws._write_store(store)
            print(f"\n✅ Admin password updated successfully!")
        else:
            print("Operation cancelled.")
        return
    
    # Create new admin
    admin = aws.create_admin(
        email=email,
        password=generate_password_hash(password),
        name=name or 'Admin'
    )
    
    print(f"\n✅ Admin account created successfully!")
    print(f"   Email: {admin['email']}")
    print(f"   Name: {admin['name']}")
    print(f"   Admin ID: {admin['adminId']}")
    print(f"\nYou can now login at: /admin/login")

if __name__ == '__main__':
    create_admin()
