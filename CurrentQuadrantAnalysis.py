import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

@dataclass
class AssetClassification:
    """Define asset classification for quadrant analysis"""
    symbol: str
    name: str
    primary_quadrant: str
    secondary_quadrant: str = None
    asset_type: str = ""
    weight: float = 1.0

class CurrentQuadrantAnalysis:
    def __init__(self, lookback_days=21):
        self.lookback_days = lookback_days
        self.asset_classifications = self._initialize_asset_classifications()
        self.quadrant_descriptions = {
            'Q1': 'Growth ↑, Inflation ↓ (Goldilocks)',
            'Q2': 'Growth ↑, Inflation ↑ (Reflation)', 
            'Q3': 'Growth ↓, Inflation ↑ (Stagflation)',
            'Q4': 'Growth ↓, Inflation ↓ (Deflation)'
        }
        # Core assets for quadrant analysis
        self.core_assets = {
            # Q1 Assets
            'QQQ': 'NASDAQ 100 (Growth)',
            'VUG': 'Vanguard Growth ETF',
            'IWM': 'Russell 2000 (Small Caps)',
            'BTC-USD': 'Bitcoin (BTC)',
            # Q2 Assets
            'XLE': 'Energy Sector ETF',
            'DBC': 'Broad Commodities ETF',
            # Q3 Assets
            'GLD': 'Gold ETF',
            'LIT': 'Lithium & Battery Tech ETF',
            # Q4 Assets
            'TLT': '20+ Year Treasury Bonds',
            'XLU': 'Utilities Sector ETF',
            'VIXY': 'Short-Term VIX Futures ETF',
        }
    
    def _initialize_asset_classifications(self) -> Dict[str, AssetClassification]:
        """Initialize asset classifications for analysis"""
        classifications = {}
        
        # Q1 Assets (Growth ↑, Inflation ↓)
        q1_assets = [
            ('QQQ', 'NASDAQ 100 (Growth)', 'Q1'),
            ('VUG', 'Vanguard Growth ETF', 'Q1'),
            ('IWM', 'Russell 2000 (Small Caps)', 'Q1'),
            ('BTC-USD', 'Bitcoin (BTC)', 'Q1'),
        ]
        # Q2 Assets (Growth ↑, Inflation ↑)
        q2_assets = [
            ('XLE', 'Energy Sector ETF', 'Q2'),
            ('DBC', 'Broad Commodities ETF', 'Q2'),
        ]
        # Q3 Assets (Growth ↓, Inflation ↑)
        q3_assets = [
            ('GLD', 'Gold ETF', 'Q3'),
            ('LIT', 'Lithium & Battery Tech ETF', 'Q3'),
        ]
        # Q4 Assets (Growth ↓, Inflation ↓)
        q4_assets = [
            ('TLT', '20+ Year Treasury Bonds', 'Q4'),
            ('XLU', 'Utilities Sector ETF', 'Q4'),
            ('UUP', 'US Dollar Index ETF', 'Q4'),
            ('VIXY', 'Short-Term VIX Futures ETF', 'Q4'),
        ]
        
        for symbol, name, quad in q1_assets + q2_assets + q3_assets + q4_assets:
            classifications[symbol] = AssetClassification(symbol, name, quad)
        
        return classifications
    
    def fetch_recent_data(self, days_back=200):
        """Fetch recent data for analysis"""
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        print(f"Fetching data from {start_date} to {end_date}...")
        
        data = {}
        failed_assets = []
        
        for symbol in self.core_assets.keys():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date)
                
                if len(hist) > 0:
                    # Clean the data - remove any NaN or zero values
                    clean_close = hist['Close'].dropna()
                    clean_close = clean_close[clean_close > 0]  # Remove zero prices
                    
                    if len(clean_close) >= 10:  # Need reasonable amount of data
                        data[symbol] = clean_close
                        print(f"✓ {symbol}: {len(clean_close)} clean days")
                    else:
                        failed_assets.append(symbol)
                        print(f"✗ {symbol}: Insufficient clean data ({len(clean_close)} days)")
                else:
                    failed_assets.append(symbol)
                    print(f"✗ {symbol}: No data")
                    
            except Exception as e:
                failed_assets.append(symbol)
                print(f"✗ {symbol}: Error - {str(e)[:50]}")
        
        if failed_assets:
            print(f"Failed to fetch: {failed_assets}")
        
        # Create DataFrame and handle alignment
        df = pd.DataFrame(data)
        
        # Remove duplicate dates by keeping the last entry for each day
        df = df.groupby(df.index.date).last()
        
        # Convert back to datetime index
        df.index = pd.to_datetime(df.index)
        
        # Forward fill missing values (for different trading schedules)
        df = df.fillna(method='ffill')
        
        # Drop rows where ALL assets are missing
        df = df.dropna(how='all')
        
        print(f"Successfully loaded {len(df.columns)} assets with {len(df)} trading days")
        return df
    
    def calculate_daily_momentum(self, price_data: pd.DataFrame) -> pd.DataFrame:
        """Calculate rolling momentum for each asset"""
        momentum_data = pd.DataFrame(index=price_data.index)
        
        for symbol in price_data.columns:
            # Calculate rolling returns over lookback period
            momentum_data[symbol] = price_data[symbol].pct_change(self.lookback_days) * 100
        
        return momentum_data
    
    def calculate_daily_quadrant_scores(self, momentum_data: pd.DataFrame) -> pd.DataFrame:
        """Calculate daily quadrant scores"""
        quadrant_scores = pd.DataFrame(index=momentum_data.index)
        
        # Initialize quadrant score columns
        for quad in ['Q1', 'Q2', 'Q3', 'Q4']:
            quadrant_scores[f'{quad}_Score'] = 0.0
            quadrant_scores[f'{quad}_Count'] = 0
        
        # Calculate scores for each day
        for date in momentum_data.index:
            daily_scores = {'Q1': 0, 'Q2': 0, 'Q3': 0, 'Q4': 0}
            daily_counts = {'Q1': 0, 'Q2': 0, 'Q3': 0, 'Q4': 0}
            
            for symbol in momentum_data.columns:
                if symbol in self.asset_classifications:
                    momentum = momentum_data.loc[date, symbol]
                    
                    if pd.notna(momentum):
                        classification = self.asset_classifications[symbol]
                        quad = classification.primary_quadrant
                        weight = classification.weight
                        
                        weighted_score = momentum * weight
                        daily_scores[quad] += weighted_score
                        daily_counts[quad] += 1
            
            # Store results for this date
            for quad in ['Q1', 'Q2', 'Q3', 'Q4']:
                quadrant_scores.loc[date, f'{quad}_Score'] = daily_scores[quad]
                quadrant_scores.loc[date, f'{quad}_Count'] = daily_counts[quad]
        
        return quadrant_scores
    
    def determine_daily_quadrant(self, quadrant_scores: pd.DataFrame) -> pd.DataFrame:
        """Determine the primary quadrant for each day"""
        results = pd.DataFrame(index=quadrant_scores.index)
        
        # Calculate normalized scores (divide by count to get average)
        for quad in ['Q1', 'Q2', 'Q3', 'Q4']:
            score_col = f'{quad}_Score'
            count_col = f'{quad}_Count'
            
            results[f'{quad}_Normalized'] = np.where(
                quadrant_scores[count_col] > 0,
                quadrant_scores[score_col] / quadrant_scores[count_col],
                0
            )
        
        # Determine primary quadrant (highest normalized score)
        quad_cols = ['Q1_Normalized', 'Q2_Normalized', 'Q3_Normalized', 'Q4_Normalized']
        results['Primary_Quadrant'] = results[quad_cols].idxmax(axis=1).str.replace('_Normalized', '')
        results['Primary_Score'] = results[quad_cols].max(axis=1)
        
        # Calculate confidence (ratio of primary to secondary)
        results['Secondary_Score'] = results[quad_cols].apply(
            lambda row: row.nlargest(2).iloc[1] if len(row.nlargest(2)) > 1 else 0, 
            axis=1
        )
        
        results['Confidence'] = np.where(
            results['Secondary_Score'] > 0,
            results['Primary_Score'] / results['Secondary_Score'],
            float('inf')
        )
        
        # Determine regime strength
        results['Regime_Strength'] = pd.cut(
            results['Confidence'],
            bins=[0, 1.2, 1.8, float('inf')],
            labels=['Weak', 'Medium', 'Strong']
        )
        
        # Add individual quadrant scores for detailed analysis
        for quad in ['Q1', 'Q2', 'Q3', 'Q4']:
            results[f'{quad}_Score'] = results[f'{quad}_Normalized']
        
        return results
    
    def analyze_current_quadrant_and_30_days(self):
        """Main analysis function - shows current quadrant and last 30 days"""
        print("=" * 60)
        print("CURRENT QUADRANT ANALYSIS + LAST 30 DAYS")
        print("=" * 60)
        
        # Fetch recent data (200 days for calculation)
        price_data = self.fetch_recent_data(days_back=200)
        
        if price_data.empty:
            print("No data available!")
            return
        
        # Calculate momentum
        momentum_data = self.calculate_daily_momentum(price_data)
        
        # Calculate quadrant scores
        quadrant_scores = self.calculate_daily_quadrant_scores(momentum_data)
        
        # Determine daily quadrant
        daily_results = self.determine_daily_quadrant(quadrant_scores)
        
        # Remove any duplicate dates (keep last entry per day)
        daily_results = daily_results.groupby(daily_results.index.date).last()
        daily_results.index = pd.to_datetime(daily_results.index)
        
        # Filter to last 30 days
        last_30_days = daily_results.tail(30)
        
        if last_30_days.empty:
            print("No recent data available!")
            return
        
        # Get current quadrant (most recent day)
        current_quadrant = last_30_days['Primary_Quadrant'].iloc[-1]
        current_score = last_30_days['Primary_Score'].iloc[-1]
        current_confidence = last_30_days['Confidence'].iloc[-1]
        current_strength = last_30_days['Regime_Strength'].iloc[-1]
        current_date = last_30_days.index[-1]
        
        # Display current quadrant
        print(f"\n🎯 CURRENT QUADRANT: {current_quadrant}")
        print("=" * 50)
        current_desc = self.quadrant_descriptions.get(current_quadrant, current_quadrant)
        print(f"Description: {current_desc}")
        print(f"Date: {current_date.strftime('%Y-%m-%d')}")
        print(f"Score: {current_score:.2f}")
        print(f"Confidence: {current_confidence:.2f}" if not np.isinf(current_confidence) else "Confidence: Very High")
        print(f"Strength: {current_strength}")
        
        # Display current quadrant scores breakdown
        print(f"\nCURRENT QUADRANT SCORES BREAKDOWN:")
        print("-" * 40)
        latest_scores = last_30_days.iloc[-1]
        for quad in ['Q1', 'Q2', 'Q3', 'Q4']:
            score = latest_scores[f'{quad}_Score']
            desc = self.quadrant_descriptions[quad].split('(')[1].rstrip(')')
            status = "👑 CURRENT" if quad == current_quadrant else ""
            print(f"{quad}: {score:6.2f} ({desc}) {status}")
        
        # Display last 30 days
        print(f"\n📊 LAST 30 DAYS QUADRANT SCORES:")
        print("=" * 75)
        print(f"{'Date':<12} {'Quad':<6} {'Score':<8} {'Q1':<7} {'Q2':<7} {'Q3':<7} {'Q4':<7} {'Strength':<8}")
        print("-" * 75)
        
        for date, row in last_30_days.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            quad = row['Primary_Quadrant']
            score = row['Primary_Score']
            strength = row['Regime_Strength']
            
            # Individual quad scores
            q1_score = row['Q1_Score']
            q2_score = row['Q2_Score']
            q3_score = row['Q3_Score']
            q4_score = row['Q4_Score']
            
            print(f"{date_str:<12} {quad:<6} {score:<8.2f} {q1_score:<7.2f} {q2_score:<7.2f} {q3_score:<7.2f} {q4_score:<7.2f} {strength:<8}")
        
        return last_30_days

def main():
    """Main function to run current quadrant analysis"""
    print("CURRENT QUADRANT ANALYSIS")
    print("=" * 50)
    print("Analyzing current market quadrant and last 30 days...")
    print("Using 21-day momentum lookback period")
    print("Fetching 200 days of data for calculation")
    print("=" * 50)
    
    # Initialize analyzer
    analyzer = CurrentQuadrantAnalysis(lookback_days=21)
    
    # Run analysis
    results = analyzer.analyze_current_quadrant_and_30_days()
    
    if results is not None:
        print(f"\n✅ Analysis completed successfully!")
        print(f"Showing last 30 days of quadrant data")
        print(f"Date range: {results.index.min().strftime('%Y-%m-%d')} to {results.index.max().strftime('%Y-%m-%d')}")
    else:
        print("❌ Analysis failed. Check data availability.")

if __name__ == "__main__":
    main()
