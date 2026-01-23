"""
Generate dummy data for testing
Creates 6 dummy users (3 males, 3 females) and simulates conversations
"""
import asyncio
import uuid
from faker import Faker
from datetime import datetime, timedelta
import random

fake = Faker()


def generate_dummy_users():
    """Generate 6 dummy users (3 males, 3 females)"""
    users = []
    
    male_names = ["John", "Michael", "David"]
    female_names = ["Sarah", "Emily", "Lisa"]
    
    for i, name in enumerate(male_names + female_names):
        user = {
            "id": str(uuid.uuid4()),
            "name": f"{name} {fake.last_name()}",
            "phone_number": fake.phone_number(),
            "email": fake.email(),
            "address": fake.address(),
            "gender": "male" if i < 3 else "female"
        }
        users.append(user)
    
    return users


def generate_businesses():
    """Generate businesses from CSV files"""
    businesses = [
        {"id": "business-1", "name": "Donrey Fashion"},
        {"id": "business-2", "name": "Junae Cosmetics"},
        {"id": "business-3", "name": "Manny Gadgets"},
        {"id": "business-4", "name": "Tesla Tech"},
        {"id": "business-5", "name": "Kemi Surprises"},
    ]
    return businesses


def generate_conversation(user, business, num_turns=20):
    """
    Generate a conversation between user and business.
    Varies from 10 to 50 dialogue turns.
    """
    conversation = []
    num_turns = random.randint(10, 50)
    
    # Initial greeting
    conversation.append({
        "role": "user",
        "content": f"Hello, I'm interested in your products",
        "timestamp": datetime.now()
    })
    
    # Simulate conversation turns
    for i in range(num_turns - 1):
        if i % 2 == 0:
            # User message
            messages = [
                f"Do you have {fake.word()} in stock?",
                f"What's the price of {fake.word()}?",
                f"I want to buy {fake.word()}",
                f"Can you deliver to {fake.city()}?",
                f"I've made the payment",
                f"Where is my order?",
            ]
            conversation.append({
                "role": "user",
                "content": random.choice(messages),
                "timestamp": datetime.now() + timedelta(minutes=i)
            })
        else:
            # AI response
            responses = [
                f"Yes, we have that in stock. It costs ${random.randint(10, 500)}",
                f"Thank you for your interest. Here are the details...",
                f"Your order has been confirmed. Payment details...",
                f"Your order is being processed",
                f"Your order is out for delivery",
            ]
            conversation.append({
                "role": "assistant",
                "content": random.choice(responses),
                "timestamp": datetime.now() + timedelta(minutes=i)
            })
    
    return {
        "user_id": user["id"],
        "business_id": business["id"],
        "conversation": conversation,
        "num_turns": len(conversation)
    }


def generate_all_conversations():
    """Generate conversations for all user-business permutations"""
    users = generate_dummy_users()
    businesses = generate_businesses()
    
    conversations = []
    for user in users:
        for business in businesses:
            conv = generate_conversation(user, business)
            conversations.append(conv)
    
    return conversations


if __name__ == "__main__":
    conversations = generate_all_conversations()
    print(f"Generated {len(conversations)} conversations")
    print(f"Total dialogue turns: {sum(c['num_turns'] for c in conversations)}")
    
    # Save to JSON or database
    import json
    with open("dummy_conversations.json", "w") as f:
        json.dump(conversations, f, indent=2, default=str)

