import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

class Candle:
    def __init__(self, open_, high, low, close):
        self.open = float(open_.iloc[0])
        self.high = float(high.iloc[0])
        self.low = float(low.iloc[0])
        self.close = float(close.iloc[0])
        self.ce = (self.high + self.low) / 2

def detect_bisi_and_backtest(df, daily_df):
    candles = []

    # Starting account balance and risk management
    initial_balance = 100000  # Starting balance of 100k
    account_balance = initial_balance
    risk_per_trade = 1000  # Risk $1000 per trade
    fee_percentage = 0.003  # 0.3% fee on each trade
    total_fees = 0  # Track total fees separately

    profitable_trades = 0
    total_trades = 0
    trade_details = []  # This will hold details of each trade

    # Keep track of dates where we've already taken a trade
    trade_taken_dates = set()

    # Create a dictionary for looking up PDL values for each date
    pdl_dict = {}
    for i in range(1, len(daily_df)):
        current_date = daily_df.index[i].date()
        prev_day_low = float(daily_df.iloc[i-1]['Low'])  # Previous day's low
        pdl_dict[current_date] = prev_day_low

    # For debugging, print some PDL values
    print("\nSample PDL values (date -> previous day's low):")
    sample_dates = list(pdl_dict.keys())[:5]  # First 5 dates
    for date in sample_dates:
        print(f"{date}: {pdl_dict[date]}")

    # Add date column to 15-min dataframe for easier processing
    df['Date'] = df.index.date

    for i in range(2, len(df) - 1):  # Start from index 2 (candle 3) and ensure we have room for candle 4
        # Extract candle data
        c1 = Candle(df.iloc[i-2:i-1]['Open'], df.iloc[i-2:i-1]['High'], df.iloc[i-2:i-1]['Low'], df.iloc[i-2:i-1]['Close'])  # Candle 1
        c2 = Candle(df.iloc[i-1:i]['Open'], df.iloc[i-1:i]['High'], df.iloc[i-1:i]['Low'], df.iloc[i-1:i]['Close'])  # Candle 2
        c3 = Candle(df.iloc[i:i+1]['Open'], df.iloc[i:i+1]['High'], df.iloc[i:i+1]['Low'], df.iloc[i:i+1]['Close'])  # Candle 3

        # Check if we have enough data for candle 4 (for entry)
        if i + 1 < len(df):
            c4 = Candle(df.iloc[i+1:i+2]['Open'], df.iloc[i+1:i+2]['High'], df.iloc[i+1:i+2]['Low'], df.iloc[i+1:i+2]['Close'])  # Candle 4 (entry candle)
        else:
            continue

        current_date = df.iloc[i].name.date()

        # Skip if we've already taken a trade today
        if current_date in trade_taken_dates:
            continue

        # Skip if we don't have PDL for this date
        if current_date not in pdl_dict:
            continue

        pdl_value = pdl_dict[current_date]  # This is correctly the PREVIOUS day's low

        # Check if PDL was swept (price went below PDL) on this candle or any previous candle today
        current_day_data = df[df['Date'] == current_date].iloc[:i+1]
        candle2_sweeps_pdl = c2.low < pdl_value
        prior_candles_swept_pdl = any(float(row['Low']) < pdl_value for _, row in current_day_data.iterrows() if _ < df.iloc[i-1].name)
        swept_pdl = prior_candles_swept_pdl or candle2_sweeps_pdl

        # For debugging specific dates
        if c2.low < pdl_value and not prior_candles_swept_pdl:
            debug_date = df.iloc[i].name.date()
            if debug_date.day % 5 == 0:  # Only print every 5th day to avoid too much output
                print(f"PDL sweep detected on {df.iloc[i].name}: c2.low ({c2.low}) < PDL ({pdl_value})")

        # Check for BISI pattern if PDL was swept
        if swept_pdl:
            # Check for BISI pattern:
            # 1. Candle 2 close must be above Candle 1 high
            # 2. Candle 3 low must be above Candle 1 high
            if c2.close > c1.high and c3.low > c1.high:
                # Entry signal after candle 3 closes
                entry_signal = True

                # Entry price is the OPEN of candle 4 (the candle after candle 3)
                entry_price = c4.open

                # Stop loss is at the low of candle 2
                sl = c2.low

                rr_multiplier = 1  # Fixed RR of 1:1
                tp = entry_price + (entry_price - sl) * rr_multiplier
                total_trades += 1
                trade_time = df.iloc[i+1].name.strftime('%Y-%m-%d %H:%M:%S')  # Candle 4's time

                # Mark that we've taken a trade for this date
                trade_taken_dates.add(current_date)

                # Check what happens after entry (candle 4 and onwards)
                if entry_signal:
                    # Calculate position size based on risk per trade (number of contracts)
                    risk_distance = entry_price - sl
                    position_size = risk_per_trade / risk_distance
                    trade_result = 0

                    # Debug position size
                    if total_trades <= 3:
                        print(f"Trade #{total_trades+1} - Entry: ${entry_price}, SL: ${sl}, Distance: ${risk_distance}")
                        print(f"Position size: {position_size} contracts (risking ${risk_per_trade})")

                    # Calculate trade value (this is the actual amount traded)
                    trade_value = risk_per_trade  # The actual amount risked in the trade

                    # Fee is 0.3% of the trade value (not the leveraged position value)
                    trade_fee = trade_value * fee_percentage
                    total_fees += trade_fee  # Add entry fee to total fees

                    for j in range(i+1, len(df)):  # Start from candle 4 onwards
                        high = float(df.iloc[j]['High'])
                        low = float(df.iloc[j]['Low'])

                        # Check for SL or TP hit
                        if low <= sl:
                            # Stop loss hit - lose exactly the risk amount
                            trade_result = -risk_per_trade
                            # Fee on exit (another 0.3% of the trade value)
                            exit_fee = trade_value * fee_percentage
                            total_fees += exit_fee
                            account_balance -= risk_per_trade + trade_fee + exit_fee
                            break  # SL hit
                        elif high >= tp:
                            # Take profit hit - gain exactly the risk amount (1:1 RR)
                            trade_result = risk_per_trade
                            # Fee on exit (another 0.3% of the trade value)
                            exit_fee = trade_value * fee_percentage
                            total_fees += exit_fee
                            account_balance += risk_per_trade - (trade_fee + exit_fee)
                            profitable_trades += 1
                            break
                    else:
                        # If neither SL nor TP was hit by the end of data
                        last_close = float(df.iloc[-1]['Close'])
                        pnl = (last_close - entry_price) * position_size
                        # Fee on exit based on the same trade value
                        exit_fee = trade_value * fee_percentage
                        total_fees += exit_fee
                        account_balance += pnl - (trade_fee + exit_fee)
                        trade_result = pnl
                        if pnl > 0:
                            profitable_trades += 1

                # Log trade details
                trade_details.append({
                    'Date': current_date,
                    'Trade Time': trade_time,
                    'Entry Candle': df.iloc[i+1].name,  # The datetime of the entry candle (candle 4)
                    'Entry Price': round(entry_price, 2),
                    'SL Price': round(sl, 2),
                    'TP Price': round(tp, 2),
                    'Result': round(trade_result, 2),
                    'PDL Value': round(pdl_value, 2)
                })

    # Calculate win rate and account balance
    win_rate = (profitable_trades / total_trades * 100) if total_trades else 0
    account_pnl = account_balance - initial_balance

    # Calculate the expected balance based purely on wins and losses
    raw_pnl = (profitable_trades * risk_per_trade) - ((total_trades - profitable_trades) * risk_per_trade)

    print(f"\nBacktest Results:")
    print(f"Total Trades Taken: {total_trades}")
    print(f"Winning Trades: {profitable_trades}")
    print(f"Losing Trades: {total_trades - profitable_trades}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Raw P&L (without fees): ${raw_pnl:.2f}")
    print(f"Initial Account Balance: ${initial_balance:.2f}")
    print(f"Final Account Balance: ${account_balance:.2f}")
    print(f"Net P&L: ${account_pnl:.2f}")
    print(f"Total Fees: ${total_fees:.2f}")  # Using the tracked total fees

    # Print trade details
    print("\nTrade Details:")
    for trade in trade_details:
        print(f"{trade['Entry Candle']} - Entry: ${trade['Entry Price']} | SL: ${trade['SL Price']} | TP: ${trade['TP Price']} | Result: ${trade['Result']} | PDL: ${trade['PDL Value']}")

    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'final_balance': account_balance,
        'trade_details': trade_details,
        'total_fees': total_fees
    }

def main():
    # Fetch data - daily for PDL and 15-minute for trading
    end_date = datetime.today()
    start_date = end_date - timedelta(days=59)  # Extend a few more days to have enough daily data for PDL

    # Get daily data for PDL calculation
    print("Fetching daily data for PDL calculation...")
    daily_df = yf.download('ES=F', start=start_date.strftime('%Y-%m-%d'), 
                          end=end_date.strftime('%Y-%m-%d'), interval='1d')

    # Get 15-minute data for trading signals
    print("Fetching 15-minute data for trading signals...")
    df = yf.download('ES=F', start=start_date.strftime('%Y-%m-%d'), 
                    end=end_date.strftime('%Y-%m-%d'), interval='15m')

    if not df.empty and not daily_df.empty:
        # Check if the timezone is already set, and if not, localize to UTC
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize('UTC')  # Localize to UTC if no timezone is set
        df.index = df.index.tz_convert('America/New_York')  # Convert to New York Time (NYT)

        if daily_df.index.tzinfo is None:
            daily_df.index = daily_df.index.tz_localize('UTC')
        daily_df.index = daily_df.index.tz_convert('America/New_York')

        # Print a sample of the daily data to verify PDL calculations
        print("\nSample of daily data (for PDL calculation):")
        print(daily_df.head(3))

        print(f"\nData loaded successfully. 15-min periods: {len(df)}, Daily periods: {len(daily_df)}")

        results = detect_bisi_and_backtest(df, daily_df)

        # Print summary statistics
        print("\nSummary:")
        print(f"Total number of trading days: {len(set(df.index.date))}")
        print(f"Days with trades: {len(set(trade['Date'] for trade in results['trade_details']))}")

    else:
        print("No data fetched. Check symbol or date range.")

if __name__ == "__main__":
    main()
    







        