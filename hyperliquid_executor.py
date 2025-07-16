import time
import math
import requests
import asyncio
from datetime import datetime
from typing import Dict, Optional
from symbol_mapping import symbol_mapper
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account

# === CONFIGURATION ===
PRIVATE_KEY = "0x04793e9c32fb5def7a646610fd7a4bbb2c769b3b110b8049ef926e8815082d30"
VAULT_ADDRESS = "0xdb9cf168543bbc5bcfdfe4c1ea542cdc8499c341"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

def initialize_exchange():
    for attempt in range(MAX_RETRIES):
        try:
            wallet = Account.from_key(PRIVATE_KEY)
            exchange = Exchange(wallet, constants.MAINNET_API_URL, vault_address=VAULT_ADDRESS)
            # Test the connection
            exchange.info.meta()
            print(f"✅ Exchange initialized with vault address: {VAULT_ADDRESS}")
            return exchange
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"⚠️ Attempt {attempt + 1} failed: {e}. Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"❌ Failed to initialize exchange after {MAX_RETRIES} attempts: {e}")
                return None

# Initialize exchange at module level with vault address
exchange = initialize_exchange()

# === Telegram config ===
TG_TOKEN = "7206335521:AAGQeuhik1SrN_qMakb9bxkI1iAJmg8A3Wo"
TG_CHAT_ID = "7119645510"

HEDGE_LONGS = ['BTC', 'ETH']

def send_telegram(msg=None, strategy_name=None, btc_beta=None, eth_beta=None, executed_trades=None, total_long=None, total_short=None, quadrant_info=None):
    try:
        if msg is None:
            msg = f"<b>{strategy_name}</b>\n\n"
            
            # Add quadrant info if available
            if quadrant_info:
                msg += f"<b>Current Market: {quadrant_info}</b>\n\n"
                
            if executed_trades and len(executed_trades) > 0:
                msg += "Executed trades (USD):\n"
                for trade in executed_trades:
                    msg += f"- {trade}\n"
            else:
                msg += "No new trades executed this run.\n"
            msg += f"\nTotal Longs (USD): <b>${total_long:,.0f}</b>\n" if total_long is not None else "\nTotal Longs (USD): <b>N/A</b>\n"
            msg += f"Total Shorts (USD): <b>${total_short:,.0f}</b>\n" if total_short is not None else "Total Shorts (USD): <b>N/A</b>\n"
            msg += f"\nBTC Beta: <b>{btc_beta:.4f}</b>\n" if btc_beta is not None else "\nBTC Beta: <b>N/A</b>\n"
            msg += f"ETH Beta: <b>{eth_beta:.4f}</b>\n" if eth_beta is not None else "ETH Beta: <b>N/A</b>\n"
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})
    except Exception as e:
        print(f"❌ Failed to send Telegram message: {e}")

def get_vault_state():
    if not exchange:
        print("❌ Exchange not initialized")
        return None
    try:
        user_state = exchange.info.user_state(VAULT_ADDRESS)
        margin_summary = user_state.get('marginSummary', {})
        positions = user_state.get('assetPositions', [])
        account_value = float(margin_summary.get('accountValue', 0))
        withdrawable = float(user_state.get('withdrawable', 0))
        return {
            'account_value': account_value,
            'withdrawable': withdrawable,
            'positions': {p['position']['coin'].upper(): float(p['position']['szi']) for p in positions if float(p['position']['szi']) != 0}
        }
    except Exception as e:
        print(f"❌ Error fetching vault state: {str(e)}")
        return None

def get_mark_price(symbol):
    try:
        hl_symbol = symbol_mapper.get_hl_symbol(symbol)
        if not hl_symbol:
            print(f"❌ Invalid symbol: {symbol}")
            return None
        orderbook = exchange.info.l2_snapshot(hl_symbol)
        if not orderbook:
            print(f"❌ No orderbook data for {hl_symbol}")
            return None
        if 'levels' in orderbook and len(orderbook['levels']) == 2:
            bids = orderbook['levels'][0]
            asks = orderbook['levels'][1]
            if bids and asks:
                best_bid = float(bids[0]['px'])
                best_ask = float(asks[0]['px'])
                mid_price = (best_bid + best_ask) / 2
                return mid_price
            else:
                print(f"❌ No valid bid/ask prices for {hl_symbol}")
                return None
        else:
            print(f"❌ Invalid orderbook structure for {hl_symbol}")
            return None
    except Exception as e:
        print(f"❌ Failed to fetch mark price for {symbol}: {e}")
        return None

def get_precision_info():
    try:
        meta = exchange.info.meta()
        return {
            item["name"].upper(): {
                "szDecimals": item.get("szDecimals", 0),
                "name": item["name"].upper()
            }
            for item in meta.get("universe", [])
        }
    except Exception as e:
        print(f"❌ Failed to fetch precision info: {e}")
        return {}

def round_price(price, sz_decimals):
    if price > 100_000:
        return round(price)
    price = float(f"{price:.5g}")
    return round(price, 6 - sz_decimals)

def round_size(size, sz_decimals):
    return round(size, sz_decimals)

def close_position(coin, size):
    try:
        hl_symbol = symbol_mapper.get_hl_symbol(coin)
        if not hl_symbol:
            print(f"❌ Could not map {coin} to HL symbol")
            return False
        side = "buy" if size < 0 else "sell"
        qty = abs(size)
        price = get_mark_price(hl_symbol)
        if price is None:
            print(f"❌ Could not get price for {hl_symbol}")
            return False
        precision_info = get_precision_info()
        coin_info = precision_info.get(hl_symbol)
        if not coin_info:
            print(f"❌ Could not get precision info for {hl_symbol}")
            return False
        rounded_price = round_price(price, coin_info["szDecimals"])
        rounded_size = round_size(qty, coin_info["szDecimals"])
        order_result = exchange.market_close(hl_symbol)
        if order_result is None:
            print("❌ Order returned None")
            return False
        if order_result["status"] == "ok":
            for status in order_result["response"]["data"]["statuses"]:
                try:
                    filled = status["filled"]
                    print(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                except KeyError:
                    print(f'Error: {status["error"]}')
            return True
        else:
            print(f"❌ Order error: {order_result.get('error', 'Unknown error')}")
            return False
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"❌ Failed to close {coin}: {e}")
        return False

def open_position(coin, size):
    try:
        hl_symbol = coin  # Always use base token for all coins
        is_buy = bool(size > 0)
        sz = abs(size)
        print(f"open_position called with coin={coin}, is_buy={is_buy}, sz={sz}")
        price = get_mark_price(hl_symbol)
        if price is None:
            print(f"❌ Could not get price for {hl_symbol}")
            return False
        precision_info = get_precision_info()
        coin_info = precision_info.get(hl_symbol)
        if not coin_info:
            print(f"❌ Could not get precision info for {hl_symbol}")
            return False
        rounded_price = float(round_price(price, coin_info["szDecimals"]))
        rounded_size = float(round_size(sz, coin_info["szDecimals"]))
        print(f"Order params for {hl_symbol}: size={size} (rounded: {rounded_size}, type: {type(rounded_size)}), price={price} (rounded: {rounded_price}, type: {type(rounded_price)}), min_size={coin_info.get('minSize', 'N/A')}, szDecimals={coin_info['szDecimals']}")
        print(f"Sending order: symbol={hl_symbol}, is_buy={is_buy}, size={rounded_size}, price=None, slippage=0.01")
        order_result = exchange.market_open(hl_symbol, is_buy, rounded_size, None, 0.01)
        if order_result is None:
            print("❌ Order returned None")
            return False
        if order_result["status"] == "ok":
            for status in order_result["response"]["data"]["statuses"]:
                try:
                    filled = status["filled"]
                    print(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                except KeyError:
                    print(f'Error: {status["error"]}')
            return True
        else:
            print(f"❌ Order error: {order_result.get('error', 'Unknown error')}")
            return False
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"❌ Failed to enter {coin}: {e}")
        return False

async def rebalance_positions(position_sizes: Dict[str, float], btc_beta: float = None, eth_beta: float = None,
                             strategy_name: str = "Unlock Arbitrage Strategy", quadrant_info: str = None):
    """Rebalance positions using Hyperliquid execution"""
    vault_state = get_vault_state()
    if not vault_state:
        print("❌ Could not fetch vault state. Exiting execution.")
        return
    current_pos = vault_state['positions']
    executed_trades = []

    print("\nCurrent positions:", current_pos)
    print("Target positions:", position_sizes)
    print(f"BTC Beta: {btc_beta}, ETH Beta: {eth_beta}")
    if quadrant_info:
        print(f"Current Market Quadrant: {quadrant_info}")

    # Track if any short positions changed
    short_positions_changed = False

    # Close positions not in new target (except BTC and ETH)
    for sym, amt in current_pos.items():
        if sym not in position_sizes and sym not in HEDGE_LONGS:
            if close_position(sym, amt):
                executed_trades.append(f"CLOSE {sym}: {amt}")
                short_positions_changed = True

    # Open new positions (except BTC and ETH)
    for sym, qty in position_sizes.items():
        if sym not in current_pos and sym not in HEDGE_LONGS:
            if open_position(sym, qty):
                executed_trades.append(f"OPEN {sym}: {qty}")
                short_positions_changed = True

    # Wait for trades to settle
    await asyncio.sleep(2)

    # Re-fetch vault state after short trades
    updated_vault_state = get_vault_state()
    if updated_vault_state:
        current_pos = updated_vault_state['positions']
        print("\nUpdated positions after short trades:", current_pos)

    # Handle BTC and ETH positions
    if btc_beta is not None and eth_beta is not None:
        print("\nProcessing hedge positions...")
        # Calculate total short exposure from actual positions
        total_short_exposure = sum(abs(float(qty)) * get_mark_price(sym) for sym, qty in current_pos.items() 
                                 if sym not in HEDGE_LONGS and float(qty) < 0)
        
        print(f"Initial short exposure calculation: ${total_short_exposure:,.2f}")
        
        # If no short exposure but we have target shorts, use those for calculation
        if total_short_exposure == 0 and any(float(qty) < 0 for sym, qty in position_sizes.items() if sym not in HEDGE_LONGS):
            print("\nNo current short exposure, using target positions for calculation")
            total_short_exposure = sum(abs(float(qty)) * get_mark_price(sym) for sym, qty in position_sizes.items() 
                                     if sym not in HEDGE_LONGS and float(qty) < 0)
            print(f"Recalculated short exposure from targets: ${total_short_exposure:,.2f}")
        
        # Calculate target BTC and ETH positions based on beta weights
        half_short_exposure = total_short_exposure / 2
        btc_target = float((half_short_exposure * btc_beta) / get_mark_price('BTC'))
        eth_target = float((half_short_exposure * eth_beta) / get_mark_price('ETH'))
        
        print(f"\nCalculating hedge positions:")
        print(f"Total short exposure: ${total_short_exposure:,.2f}")
        print(f"Half short exposure: ${half_short_exposure:,.2f}")
        print(f"BTC target: {btc_target:.4f} (${btc_target * get_mark_price('BTC'):,.2f})")
        print(f"ETH target: {eth_target:.4f} (${eth_target * get_mark_price('ETH'):,.2f})")
        
        # Handle BTC position
        current_btc = float(current_pos.get('BTC', 0))
        print(f"\nBTC Position Check:")
        print(f"Current BTC: {current_btc:.4f}")
        print(f"Target BTC: {btc_target:.4f}")
        print(f"Short positions changed: {short_positions_changed}")
        print(f"Has short exposure: {total_short_exposure > 0}")
        
        if abs(current_btc) < 0.001 and total_short_exposure > 0:  # If no BTC position exists and we have shorts
            print(f"Opening new BTC position: {btc_target:.4f}")
            if open_position('BTC', btc_target):
                executed_trades.append(f"OPEN BTC: {btc_target}")
        elif short_positions_changed and abs(current_btc - btc_target) > 0.001:  # Adjust if shorts changed
            delta = btc_target - current_btc
            print(f"Adjusting BTC position by delta: {delta:.4f}")
            if open_position('BTC', delta):
                executed_trades.append(f"ADJUST BTC: {delta:.4f}")
        
        # Handle ETH position
        current_eth = float(current_pos.get('ETH', 0))
        print(f"\nETH Position Check:")
        print(f"Current ETH: {current_eth:.4f}")
        print(f"Target ETH: {eth_target:.4f}")
        print(f"Short positions changed: {short_positions_changed}")
        print(f"Has short exposure: {total_short_exposure > 0}")
        
        if abs(current_eth) < 0.001 and total_short_exposure > 0:  # If no ETH position exists and we have shorts
            print(f"Opening new ETH position: {eth_target:.4f}")
            if open_position('ETH', eth_target):
                executed_trades.append(f"OPEN ETH: {eth_target}")
        elif short_positions_changed and abs(current_eth - eth_target) > 0.001:  # Adjust if shorts changed
            delta = eth_target - current_eth
            print(f"Adjusting ETH position by delta: {delta:.4f}")
            if open_position('ETH', delta):
                executed_trades.append(f"ADJUST ETH: {delta:.4f}")

    # Wait for trades to settle
    await asyncio.sleep(2)

    # Re-fetch vault state and recalculate totals
    final_vault_state = get_vault_state()
    updated_positions = final_vault_state['positions'] if final_vault_state else position_sizes
    mark_prices = {sym: get_mark_price(sym) for sym in updated_positions.keys()}
    total_long = sum(abs(float(qty)) * mark_prices[sym] for sym, qty in updated_positions.items() if float(qty) > 0 and mark_prices[sym])
    total_short = sum(abs(float(qty)) * mark_prices[sym] for sym, qty in updated_positions.items() if float(qty) < 0 and mark_prices[sym])

    print("\n✅ Strategy execution completed")
    send_telegram(
        strategy_name=strategy_name,
        btc_beta=btc_beta,
        eth_beta=eth_beta,
        executed_trades=executed_trades,
        total_long=total_long,
        total_short=total_short,
        quadrant_info=quadrant_info
    )
