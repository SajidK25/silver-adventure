# bot.py

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
from coinpayments import CoinPaymentsAPI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize bot with token from environment variable
TOKEN = os.getenv('6999508387:AAGdO-izRKzKON5Oh7Ifquo8UqhA7DmgEHU')
bot = Bot(token=TOKEN)

# Admin ID and database path
ADMIN_ID = 1525215637  # Replace with your Telegram user ID
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'subscriptions.db')

# CoinPayments.net API credentials from environment variables
CP_PUBLIC_KEY = os.getenv('d034ec4829d0b8688d158f718e293bdda9cdcec06cf0fae816cebfc7a2bd616c')
CP_PRIVATE_KEY = os.getenv('0791fd1446A1b7c1947DF58b0520bb6f5d6BCF5d905ABf1ABe5a4022f35B6e5d')
cp = CoinPaymentsAPI(public_key=CP_PUBLIC_KEY, private_key=CP_PRIVATE_KEY)

# Terms and conditions message
TERMS_AND_CONDITIONS = '''
1. We do not guarantee 100% winnings as these are just predictions.
2. Payment once completed no refunds.
3. Any abuse to staff members will result in a direct ban.
4. All inquiries and complaints should be directed to our support.
5. By continuing you agree to all our terms and conditions.
'''


# Helper function to create SQLite connection
def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        logger.info("Connected to SQLite database at {}".format(DATABASE_PATH))
    except sqlite3.Error as e:
        logger.error(f"Error connecting to SQLite database: {e}")
    return conn


# Ensure database is set up
def setup_database():
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
                                user_id INTEGER PRIMARY KEY,
                                subscription_type TEXT,
                                start_date TEXT,
                                next_renewal TEXT,
                                amount_paid REAL,
                                payment_status TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS user_agreements (
                                user_id INTEGER PRIMARY KEY)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS predictions (
                                option TEXT PRIMARY KEY,
                                prediction TEXT)''')
            conn.commit()
            logger.info("Database setup complete.")
        except sqlite3.Error as e:
            logger.error(f"Error setting up database: {e}")
        finally:
            conn.close()


setup_database()


# Start command handler
def start_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    first_name = update.message.from_user.first_name
    logger.info(f"User {user_id} started the bot.")
    try:
        gif_path = os.path.join(os.path.dirname(__file__), "TheTipster.gif")  # Path to the uploaded GIF file
        bot.send_animation(chat_id, animation=open(gif_path, 'rb'),
                           caption=f"Welcome {first_name}🎉 Enjoy more winnings with our highly rated well analyzed daily and weekly sports prediction tips🍻")
        bot.send_message(chat_id, f"Hello {first_name},\n{TERMS_AND_CONDITIONS}", reply_markup=inline_terms_buttons())
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        bot.send_message(chat_id, "An error occurred. Please try again later.")


# Inline keyboard for terms agreement
def inline_terms_buttons():
    keyboard = [[InlineKeyboardButton("Agree", callback_data='agree')]]
    return InlineKeyboardMarkup(keyboard)


# Terms agreement handler
def inline_terms_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    if data == 'agree':
        logger.info(f"User {user_id} agreed to the terms and conditions.")
        conn = create_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO user_agreements (user_id) VALUES (?)", (user_id,))
                conn.commit()
                bot.send_message(chat_id,
                                 "Thank you for agreeing to the terms and conditions. Please choose a subscription plan:",
                                 reply_markup=subscription_buttons())
            except sqlite3.Error as e:
                logger.error(f"Error in inline_terms_callback: {e}")
                bot.send_message(chat_id, "An error occurred while recording your agreement. Please try again.")
            finally:
                conn.close()
    else:
        logger.warning(f"Unexpected callback data: {data}")


# Subscription buttons
def subscription_buttons():
    keyboard = [
        [InlineKeyboardButton("Biweekly - $5", callback_data='biweekly')],
        [InlineKeyboardButton("Monthly - $10", callback_data='monthly')]
    ]
    return InlineKeyboardMarkup(keyboard)


# Subscription payment handler
def handle_subscription_payment(user_id, subscription_type):
    amount = 5 if subscription_type == 'biweekly' else 10
    try:
        # Create a transaction using CoinPayments API
        result = cp.create_transaction(amount=amount, currency1='USD', currency2='BTC', buyer_email='buyer@example.com')
        if result['error'] == 'ok':
            payment_url = result['result']['checkout_url']
            address = result['result']['address']
            txn_id = result['result']['txn_id']

            conn = create_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    start_date = datetime.now()
                    next_renewal = start_date + timedelta(days=14 if subscription_type == 'biweekly' else 30)
                    cursor.execute('''
                        INSERT OR REPLACE INTO subscriptions (user_id, subscription_type, start_date, next_renewal, amount_paid, payment_status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''', (
                    user_id, subscription_type, start_date.isoformat(), next_renewal.isoformat(), amount, 'pending'))
                    conn.commit()
                except sqlite3.Error as e:
                    logger.error(f"Error recording subscription in database: {e}")
                finally:
                    conn.close()
            return payment_url, txn_id
        else:
            logger.error(f"CoinPayments API error: {result['error']}")
            return None, None
    except Exception as e:
        logger.error(f"Error creating CoinPayments transaction: {e}")
        return None, None


# Handle subscription callbacks
def inline_subscription_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    first_name = query.from_user.first_name
    data = query.data

    if data in ['biweekly', 'monthly']:
        logger.info(f"User {user_id} selected {data} subscription.")
        payment_url, txn_id = handle_subscription_payment(user_id, data)
        if payment_url:
            bot.send_message(chat_id,
                             f"{first_name}, please complete your payment using the following link: {payment_url}")
            # Schedule a job to check payment confirmation
            context.job_queue.run_once(check_payment_status, 60,
                                       context={'txn_id': txn_id, 'user_id': user_id, 'chat_id': chat_id,
                                                'first_name': first_name, 'subscription_type': data}, name=str(user_id))
        else:
            bot.send_message(chat_id,
                             f"Sorry {first_name}, an error occurred while generating the payment link. Please try again.")
    else:
        logger.warning(f"Unexpected callback data: {data}")
        bot.send_message(chat_id, f"Invalid subscription plan selected, {first_name}.")


# Check payment status
def check_payment_status(context: CallbackContext):
    job = context.job
    txn_id = job.context['txn_id']
    user_id = job.context['user_id']
    chat_id = job.context['chat_id']
    first_name = job.context['first_name']
    subscription_type = job.context['subscription_type']

    try:
        result = cp.get_tx_info(txn_id)
        if result['error'] == 'ok':
            status = result['result']['status']
            confirmations = result['result']['received_confirms']
            if status >= 100 or confirmations >= 3:
                # Payment confirmed
                conn = create_connection()
                if conn:
                    try:
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE subscriptions
                            SET payment_status = ?
                            WHERE user_id = ?
                            ''', ('confirmed', user_id))
                        conn.commit()
                        bot.send_message(chat_id,
                                         f"Congratulations {first_name}! You are now a premium TheTipster user.")
                        bot.send_message(chat_id, "Please select an option below:", reply_markup=prediction_buttons())
                    except sqlite3.Error as e:
                        logger.error(f"Error updating subscription status in database: {e}")
                    finally:
                        conn.close()
            else:
                # Reschedule the job if not confirmed
                context.job_queue.run_once(check_payment_status, 60,
                                           context={'txn_id': txn_id, 'user_id': user_id, 'chat_id': chat_id,
                                                    'first_name': first_name, 'subscription_type': subscription_type},
                                           name=str(user_id))
        else:
            logger.error(f"CoinPayments API error: {result['error']}")
    except Exception as e:
        logger.error(f"Error checking CoinPayments transaction status: {e}")


# Prediction buttons
def prediction_buttons():
    keyboard = [
        [InlineKeyboardButton("2-5 odds", callback_data='2-5 odds')],
        [InlineKeyboardButton("BTT", callback_data='BTT')],
        [InlineKeyboardButton("Over 1.5", callback_data='Over 1.5')],
        [InlineKeyboardButton("Weekly Slip", callback_data='Weekly Slip')],
        [InlineKeyboardButton("Weekly Rollover", callback_data='Weekly Rollover')],
        [InlineKeyboardButton("Special Bet", callback_data='Special Bet')],
        [InlineKeyboardButton("High Risk Bet", callback_data='High Risk Bet')],
        [InlineKeyboardButton("Support", url='https://t.me/thetipster_support')],
        [InlineKeyboardButton("Profile", callback_data='profile')]
    ]
    return InlineKeyboardMarkup(keyboard)


# Send predictions handler
def send_prediction(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT next_renewal FROM subscriptions WHERE user_id = ?", (user_id,))
            subscription = cursor.fetchone()

            if subscription:
                next_renewal_date = datetime.fromisoformat(subscription[0])
                if datetime.now() < next_renewal_date:
                    cursor.execute("SELECT prediction FROM predictions WHERE option = ?",
                                   (update.message.text.strip(),))
                    prediction = cursor.fetchone()
                    if prediction:
                        bot.send_message(chat_id, f"Prediction: \n\n{update.message.text.strip()}: {prediction[0]}")
                    else:
                        bot.send_message(chat_id,
                                         f"Prediction: \n\n{update.message.text.strip()}: No prediction available yet.")
                else:
                    bot.send_message(chat_id, "Your subscription has expired. Please renew your subscription.")
                    logger.info(f"User {user_id}'s subscription has expired.")
            else:
                bot.send_message(chat_id, "Please subscribe first by selecting a plan.")
                logger.info(f"User {user_id} tried to access predictions without a subscription.")
    except sqlite3.Error as e:
        logger.error(f"Error sending prediction to user {user_id}: {e}")
        bot.send_message(chat_id, "An error occurred while fetching the prediction. Please try again.")
    finally:
        if conn:
            conn.close()


# Profile button handler
def profile_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    first_name = query.from_user.first_name

    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT subscription_type, start_date, next_renewal, amount_paid, payment_status FROM subscriptions WHERE user_id = ?",
                (user_id,))
            subscription = cursor.fetchone()

            if subscription:
                subscription_type, start_date, next_renewal, amount_paid, payment_status = subscription
                days_remaining = (datetime.fromisoformat(next_renewal) - datetime.now()).days
                profile_info = (
                    f"User ID: {user_id}\n"
                    f"Subscription Type: {subscription_type}\n"
                    f"Days Remaining: {days_remaining}\n"
                    f"Amount Paid: ${amount_paid}\n"
                    f"Payment Status: {payment_status}"
                )
                bot.send_message(chat_id, profile_info)
                logger.info(f"User {user_id} accessed their profile information.")
            else:
                bot.send_message(chat_id,
                                 f"No subscription found. Please subscribe first by selecting a plan, {first_name}.")
                logger.info(f"User {user_id} tried to access profile without a subscription.")
    except sqlite3.Error as e:
        logger.error(f"Error accessing profile for user {user_id}: {e}")
        bot.send_message(chat_id, f"An error occurred while accessing your profile. Please try again, {first_name}.")
    finally:
        if conn:
            conn.close()


# Update prediction (Admin only)
def update_prediction(prediction_type, prediction_text, user):
    if user.user_id != ADMIN_ID:
        logger.warning(f"Unauthorized prediction update attempt by user {user.user_id}")
        bot.send_message(user.chat_id, "Unauthorized access. Only admins can add predictions.")
        return

    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO predictions (option, prediction)
                VALUES (?, ?)
                ''', (prediction_type, prediction_text))
            conn.commit()
            logger.info(f"Prediction updated: {prediction_type} - {prediction_text}")
            bot.send_message(user.chat_id, "Prediction updated successfully.")
    except sqlite3.Error as e:
        logger.error(f"Error updating prediction: {e}")
        bot.send_message(user.chat_id, "An error occurred while updating the prediction. Please try again.")
    finally:
        if conn:
            conn.close()


# Handle incoming messages
def handle_message(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    message_text = update.message.text.strip()

    if update.message.chat.type == 'private':
        if message_text.lower().startswith('/predict '):
            prediction_type = message_text[len('/predict '):].strip()
            send_prediction(update, context, prediction_type)
        elif message_text.lower().startswith('/update '):
            if user_id == ADMIN_ID:
                parts = message_text[len('/update '):].strip().split(' ', 1)
                if len(parts) == 2:
                    prediction_type, prediction_text = parts
                    update_prediction(prediction_type, prediction_text, update.message.from_user)
                else:
                    bot.send_message(chat_id, "Invalid update format. Use /update <prediction_type> <prediction_text>")
            else:
                bot.send_message(chat_id, "Unauthorized access. Only admins can add predictions.")
        else:
            bot.send_message(chat_id,
                             "Invalid command. Please use /predict <type> to get predictions or /update <type> <text> to update (Admin only).")


# Notify user to renew subscription
def notify_user_to_renew(context: CallbackContext):
    job = context.job
    chat_id = job.context['chat_id']
    first_name = job.context['first_name']
    bot.send_message(chat_id,
                     f"Hi {first_name}, your subscription is about to end. Please renew your subscription to continue enjoying our services.",
                     reply_markup=subscription_buttons())


# Schedule subscription renewal notifications
def schedule_renewal_notifications(context: CallbackContext):
    conn = create_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, next_renewal FROM subscriptions WHERE payment_status = 'confirmed'")
            subscriptions = cursor.fetchall()
            for subscription in subscriptions:
                user_id, next_renewal = subscription
                chat_id = user_id  # Assuming chat_id is the same as user_id
                first_name = "User"  # Retrieve the user's first name from your database if available
                renewal_date = datetime.fromisoformat(next_renewal)
                if (renewal_date - datetime.now()).days <= 2:
                    context.job_queue.run_once(notify_user_to_renew, (renewal_date - datetime.now()).total_seconds(),
                                               context={'chat_id': chat_id, 'first_name': first_name},
                                               name=str(user_id))
        except sqlite3.Error as e:
            logger.error(f"Error scheduling renewal notifications: {e}")
        finally:
            conn.close()


# Rate limiting middleware
class RateLimiter:
    def __init__(self, limit=5):
        self.limit = limit
        self.requests = {}

    def is_allowed(self, user_id):
        if user_id not in self.requests:
            self.requests[user_id] = []
        self.requests[user_id] = [timestamp for timestamp in self.requests[user_id] if
                                  timestamp > datetime.now() - timedelta(minutes=1)]
        if len(self.requests[user_id]) < self.limit:
            self.requests[user_id].append(datetime.now())
            return True
        return False


rate_limiter = RateLimiter()


def rate_limited(func):
    def wrapper(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        if rate_limiter.is_allowed(user_id):
            return func(update, context)
        else:
            update.message.reply_text("You are sending too many requests. Please slow down.")

    return wrapper


# Main function to start the bot
def main():
    updater = Updater(token=TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', start_command))
    dispatcher.add_handler(CallbackQueryHandler(inline_terms_callback, pattern='^agree$'))
    dispatcher.add_handler(CallbackQueryHandler(inline_subscription_callback, pattern='^(biweekly|monthly)$'))
    dispatcher.add_handler(CallbackQueryHandler(profile_callback, pattern='^profile$'))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, rate_limited(handle_message)))

    # Schedule renewal notifications
    updater.job_queue.run_repeating(schedule_renewal_notifications, interval=86400, first=0)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
