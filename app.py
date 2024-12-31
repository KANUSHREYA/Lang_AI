from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from typing import List
import psycopg2
import hashlib
from datetime import datetime
import random
import string
from datetime import datetime
from fastapi import Query

# Modify the UserRegistration model to include the generated user code
class UserRegistration(BaseModel):
    name: str
    email: str
    password: str
    user_code: str
    referred_by: str
    total_points: int

class WalletHistory(BaseModel):
    points: int
    date: str  
    referred_from: int
    referred_to: int# You might want to use a datetime field

# User model for PATCH request
class UserPatch(BaseModel):
    name: str
    email: str

app = FastAPI()

# Database connection parameters
conn_params = {
    "dbname": "referral_system",
    "user": "postgres",
    "password": "admin",
    "host": "127.0.0.1",
    "port": "5432"
}
# Function to establish database connection
def get_connection():
    try:
        conn = psycopg2.connect(**conn_params)
        return conn
    except psycopg2.Error as e:
        print("Error connecting to database:", e)

# Function to hash password
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def generate_unique_code():
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choices(characters, k=5))
    # Check if the code is already used, if yes, generate a new one recursively
    if check_code_existence(code):
        return generate_unique_code()
    return code

# Function to check if the generated code already exists in the database
def check_code_existence(code):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM user_registration WHERE user_code = %s", (code,))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count > 0

def update_total_points(referred_by: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Count the number of occurrences where referred_by matches referred_from in wallet_history table
        cur.execute("SELECT COUNT(*) FROM wallet_history WHERE referred_from = %s", (referred_by,))
        referral_count = cur.fetchone()[0]

        # Calculate total points for the user
        total_points = referral_count * 100  # Assuming each referral earns 100 points

        # Update total points for the user in user_registration table
        cur.execute("UPDATE user_registration SET total_points = %s WHERE id = %s", (total_points, referred_by))

        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        print("Error updating total points:", e)
    finally:
        cur.close()
        conn.close()

@app.post("/register/")
async def register_user(user: UserRegistration):
    conn = get_connection()
    cur = conn.cursor()
    try:
        hashed_password = hash_password(user.password)
        user_code = generate_unique_code()
        
        # Check if the user has been referred by someone
        if user.referred_by:
            cur.execute(
                "INSERT INTO user_registration (name, email, password, user_code, referred_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (user.name, user.email, hashed_password, user_code, user.referred_by)
            )
        else:
            cur.execute(
                "INSERT INTO user_registration (name, email, password, user_code) VALUES (%s, %s, %s, %s) RETURNING id",
                (user.name, user.email, hashed_password, user_code)
            )
        
        user_id = cur.fetchone()[0]       
        # If the user is referred by someone, record points for the referrer
        if user.referred_by:
            cur.execute(
                "INSERT INTO wallet_history (points, date, referred_from, referred_to) VALUES (%s, %s, %s, %s)",
                (100, datetime.now().strftime("%Y-%m-%d"), user.referred_by, user_id)
            )
            # Update total points for the referrer
            update_total_points(user.referred_by)  # Update the referrer's total points
        
        conn.commit()
        return {"user_id": user_id}
    except Exception as e:
        print(e)
    finally:
        cur.close()
        conn.close()


@app.delete("/users/{user_id}")
async def delete_user(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Check if the user exists
        cur.execute("SELECT 1 FROM user_registration WHERE id = %s", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete the user
        cur.execute("DELETE FROM user_registration WHERE id = %s", (user_id,))
        conn.commit()
        
        return {"message": "User deleted successfully"}
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail="Error deleting user")
    finally:
        cur.close()
        conn.close()

def get_referral_name(user_id, conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM user_registration WHERE user_code = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        else:
            return None
    finally:
        cur.close()

def get_referred_persons(user_id, conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT name, email FROM user_registration WHERE user_code = %s", (user_id,))
        rows = cur.fetchall()
        referred_persons = []
        for row in rows:
            referred_persons.append({
                "name": row[0],
                "email": row[1]
            })
        return referred_persons
    finally:
        cur.close()

@app.get("/users_list/")
async def list_users(limit: int = Query(10, ge=1, le=100), skip: int = Query(0, ge=0), search: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = "SELECT * FROM user_registration"
        if search:
            # Convert search term to lowercase for case-insensitive comparison
            search_term = search.lower()
            query += f" WHERE LOWER(name) LIKE '%{search_term}%' OR LOWER(email) LIKE '%{search_term}%'"
        query += f" LIMIT %s OFFSET %s"
        cur.execute(query, (limit, skip))
        rows = cur.fetchall()
        users = []
        for row in rows:
            users.append({
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "user_code": row[3],  # Assuming user_code is in the 4th column
                "referred_by": row[4],  # Assuming referred_by is in the 5th column
                "total_points": row[5]  # Assuming total_points is in the 6th column
            })
        return users
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail="Error fetching users")
    finally:
        cur.close()
        conn.close()

from typing import List, Optional

from fastapi import HTTPException

@app.get("/user_list/{user_id}")
async def get_user_info(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Get user's information and points given by each user to the user_id passed
        cur.execute("SELECT u.name AS refer_by, r.name AS user_name, wh.date, wh.points, \
                            u.email, u.user_code \
                     FROM user_registration u \
                     LEFT JOIN wallet_history wh ON u.id = wh.referred_from \
                     LEFT JOIN user_registration r ON wh.referred_to = r.id \
                     WHERE u.id = %s", (user_id,))
        referral_records = cur.fetchall()

        formatted_records = []
        for record in referral_records:
            refer_by, user_name, date, points, email, user_code = record
            if refer_by is None:  # User has not referred anyone
                formatted_records.append({
                    "name": user_name,
                    "email": email,
                    "user_code": user_code
                })
            else:  # User has referred someone
                formatted_records.append({
                    "refer_by": refer_by,
                    "user_name": user_name,
                    "date": date,
                    "points": points,
                })

        return formatted_records
    except psycopg2.Error as e:
        print("Error fetching user information:", e)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        cur.close()
        conn.close()

# PATCH endpoint to update user details
@app.patch("/update_user/{user_id}")
async def update_user(user_id: int, user_patch: UserPatch):
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Check if user exists
        cur.execute("SELECT * FROM user_registration WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Update user details
        cur.execute("UPDATE user_registration SET name = %s, email = %s WHERE id = %s",
                    (user_patch.name, user_patch.email, user_id))
        
        conn.commit()
        return {"message": "User details updated successfully"}

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail="Error updating user details")
    finally:
        cur.close()
        conn.close()
