# -*- coding: utf-8 -*-
"""
Created on Mon Nov 21 23:12:48 2022

@author: gyzdm
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


class StockRadar:
    def __init__(self, watch_list):
        self.watch_list = watch_list
        self.data = None
        self.sma = None
        self.backtrack_list = []
        
    def __load_data(self):
        watch_list_string = " ".join(self.watch_list)
        self.data = yf.download(watch_list_string, start="2020-01-01")
        return
    
    def getMovingAverage(self):
        if not self.data:
            self.__load_data()
        window_sizes = [5,10,20,30,50,100,200]
        self.sma_tokens = ["SMA{}".format(window_size) for window_size in window_sizes]
        #self.sma = self.data.loc[:,(["Close"],self.watch_list)]
        columns = pd.MultiIndex.from_product([self.sma_tokens, self.watch_list], names=['sma_type','token'])
        self.sma = pd.DataFrame(columns = columns)
        for window_size in window_sizes:
            sma_token = "SMA{}".format(window_size)
            for stock_token in self.watch_list:
                stock_close_prices = self.data["Close"][stock_token].to_frame()
                sma_df = stock_close_prices[stock_token].rolling(window_size).mean()
                self.sma.loc[:,(sma_token,stock_token)] = sma_df
                #self.sma.dropna(inplace=True)
        #self.sma.loc[:,(slice(None),['SPY'])].plot()
        #plt.show()
        return self.sma
    
    def checkSMACrossing(self):
        if not self.sma:
            self.getMovingAverage()
        stock_crossing_tag = []
        data_365day = self.data["Close"]
        data_30day = data_365day[-30:-1]
        for stock_token in self.watch_list:
            close_today = self.data["Close"][stock_token][-1]
            close_yesterday = self.data["Close"][stock_token][-2]
            high_today =  self.data["High"][stock_token][-1]
            low_today =  self.data["Low"][stock_token][-1]
            change = close_today/close_yesterday-1
            data_365day = self.data["Close"][stock_token]
            data_30day = data_365day[-30:-1]
            rank365 = data_365day.rank(pct=True)
            rank30 = data_30day.rank(pct=True)
            for sma_token in self.sma_tokens:
                sma_today = self.sma[sma_token][stock_token][-1]
                sma_yesterday = self.sma[sma_token][stock_token][-2]
                if close_today > sma_today and close_yesterday < sma_yesterday:
                    stock_crossing_tag.append("{0} Up Crossing {1} change:{2:+.1%} rank30:{3:.1%} rank365:{4:.1%}".format(stock_token,sma_token, change,rank30[-1],rank365[-1]))                    
                elif close_today < sma_today and close_yesterday > sma_yesterday:
                    stock_crossing_tag.append("{0} Down Crossing {1} change:{2:+.1%} rank30:{3:.1%} rank365:{4:.1%}".format(stock_token,sma_token, change,rank30[-1],rank365[-1]))
                elif high_today > sma_today and close_yesterday < sma_yesterday:
                    stock_crossing_tag.append("{} Failed Up Crossing {}".format(stock_token,sma_token))
                elif low_today < sma_today and close_yesterday > sma_yesterday:
                    stock_crossing_tag.append("{} Failed Down Crossing {}".format(stock_token,sma_token))
        return stock_crossing_tag
    
    def backtrack_sma(self):
        if self.sma is None:
            self.getMovingAverage()
        transactions = []
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            initial_balance = 10000
            # SMA strategy
            for sma_token in self.sma_tokens:
                shares = 0
                balance = 0
                next_year = True
                for row in range(close_prices.shape[0]):
                    sma_today = self.sma[sma_token][stock_token][row]
                    sma_yesterday = self.sma[sma_token][stock_token][row-1]
                    if pd.isna(sma_today) or pd.isna(sma_yesterday):
                        continue
                    close_today = close_prices[row]
                    close_yesterday = close_prices[row-1]
                    if next_year:
                        year = close_prices.index[row].year
                        next_year = False
                        balance += initial_balance
                        year_start_asset = shares*close_prices[row] + balance
                    if close_today > sma_today and close_yesterday < sma_yesterday:
                        if balance > 0:
                            shares_to_buy = balance/close_today
                            shares += shares_to_buy
                            total_asset = shares*close_today
                            balance = 0
                            transactions.append("{4} {0} {5} buy {1:.1f} shares @price:{2:.2f} $ total assets {3:.2f} $".format(stock_token,shares_to_buy,close_today,total_asset,close_prices.index[row].strftime("%Y-%m-%d"),sma_token))                    
                    elif close_today < sma_today and close_yesterday > sma_yesterday:
                        if shares>0:
                            shares_to_sell = shares
                            balance_credits = shares*close_today
                            shares =0
                            balance+=balance_credits
                            total_asset = balance
                            transactions.append("{4} {0} {5} sell {1:.1f} shares @price:{2:.2f} $ total assets {3:.2f} $".format(stock_token,shares_to_sell,close_today,total_asset,close_prices.index[row].strftime("%Y-%m-%d"),sma_token))  
                    if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                        total_asset = shares*close_prices[row]+balance
                        performance = total_asset/year_start_asset - 1
                        transactions.append("{0} {5} {6} final total assets: {3:.2f} $ performance: {4:.1%} {1:.1f} shares @price:{2:.2f} $".format(stock_token,shares,close_prices[-1],total_asset, performance,sma_token,year))  
                        self.backtrack_list.append([stock_token,sma_token,year,performance])   
                        next_year = True
        return
    
    def backtrack_all_in(self):
        sma_token = 'All_In'
        initial_balance = 10000
        transactions = []
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            shares = 0
            balance = initial_balance
            for row in range(close_prices.shape[0]):
                if shares == 0:
                    shares = balance/close_prices[row]
                    year = close_prices.index[row].year
                    transactions.append("{4} {0} {5} buy {1:.1f} shares @price:{2:.2f} $ total assets {3:.2f} $"
                                        .format(stock_token,shares,close_prices[row], balance,close_prices.index[row].strftime("%Y-%m-%d"),sma_token))                    
                    balance = 0
                if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                    total_asset = shares*close_prices[row]+balance
                    performance = total_asset/initial_balance - 1
                    transactions.append("{0} {5} {6} final total assets: {3:.2f} $ performance: {4:.1%} {1:.1f} shares @price:{2:.2f} $".format(stock_token,shares,close_prices[row],total_asset, performance,sma_token,year))  
                    self.backtrack_list.append([stock_token,sma_token,year,performance])   
                    shares = 0
                    balance = initial_balance
        return
                
    def backtrack_automatic(self):
        sma_token = 'Automatic_Daily'
        initial_balance = 10000
        transactions = []
        
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            shares = 0
            next_year = True
            for row in range(close_prices.shape[0]):
                if next_year:
                    year = close_prices.index[row].year
                    next_year = False
                    ndays = len(close_prices[close_prices.index.year == year])
                    balance = initial_balance
                    periodic_invest_fund = initial_balance/ndays
                    year_start_asset = shares*close_prices[row] + balance
                new_shares=periodic_invest_fund/close_prices[row]
                shares+=new_shares
                balance-=periodic_invest_fund
                transactions.append("{4} {0} {5} buy {1:.1f} shares @price:{2:.2f} $ total assets {3:.2f} $"
                                    .format(stock_token,new_shares,close_prices[row], balance+shares*close_prices[row],close_prices.index[row].strftime("%Y-%m-%d"),sma_token))                    
                if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                    total_asset = shares*close_prices[row]
                    performance = total_asset/year_start_asset - 1
                    transactions.append("{0} {5} {6} final total assets: {3:.2f} $ performance: {4:.1%} {1:.1f} shares @price:{2:.2f} $".format(stock_token,shares,close_prices[row],total_asset, performance,sma_token,year))  
                    self.backtrack_list.append([stock_token,sma_token,year,performance])   
                    next_year = True
        sma_token = 'Automatic_Monthly'
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            shares = 0
            next_year = True
            for row in range(close_prices.shape[0]):
                if next_year:
                    year = close_prices.index[row].year
                    next_year = False
                    ndays = len(close_prices[close_prices.index.year == year])
                    month = 12
                    period = ndays//month
                    balance = initial_balance
                    periodic_invest_fund = initial_balance/month
                    year_start_asset = shares*close_prices[row] + balance
                if row % period == 0 and balance*1.1>=periodic_invest_fund:
                    new_shares=periodic_invest_fund/close_prices[row]
                    shares+=new_shares
                    balance-=periodic_invest_fund
                    transactions.append("{4} {0} {5} buy {1:.1f} shares @price:{2:.2f} $ total assets {3:.2f} $"
                                        .format(stock_token,new_shares,close_prices[row], balance+shares*close_prices[row],close_prices.index[row].strftime("%Y-%m-%d"),sma_token))                    
                if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                    total_asset = shares*close_prices[row]
                    performance = total_asset/year_start_asset - 1
                    transactions.append("{0} {5} {6} final total assets: {3:.2f} $ performance: {4:.1%} {1:.1f} shares @price:{2:.2f} $".format(stock_token,shares,close_prices[row],total_asset, performance,sma_token,year))  
                    self.backtrack_list.append([stock_token,sma_token,year,performance])   
                    next_year = True
        sma_token = 'Automatic_Biweekly'
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            shares = 0
            next_year = True
            for row in range(close_prices.shape[0]):
                if next_year:
                    year = close_prices.index[row].year
                    next_year = False
                    ndays = len(close_prices[close_prices.index.year == year])
                    n_biweekly = 24
                    period = ndays//n_biweekly
                    balance = initial_balance
                    periodic_invest_fund = initial_balance/n_biweekly
                    year_start_asset = shares*close_prices[row] + balance
                if row % period == 0 and balance*1.1>=periodic_invest_fund:
                    new_shares=periodic_invest_fund/close_prices[row]
                    shares+=new_shares
                    balance-=periodic_invest_fund
                    transactions.append("{4} {0} {5} buy {1:.1f} shares @price:{2:.2f} $ total assets {3:.2f} $"
                                        .format(stock_token,new_shares,close_prices[row], balance+shares*close_prices[row],close_prices.index[row].strftime("%Y-%m-%d"),sma_token))                    
                if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                    total_asset = shares*close_prices[row]
                    performance = total_asset/year_start_asset - 1
                    transactions.append("{0} {5} {6} final total assets: {3:.2f} $ performance: {4:.1%} {1:.1f} shares @price:{2:.2f} $".format(stock_token,shares,close_prices[row],total_asset, performance,sma_token,year))  
                    self.backtrack_list.append([stock_token,sma_token,year,performance])   
                    next_year = True
        return
    
    def backtrack(self):
        stock_token = "SPY"
        results = {}
        initial_balance = 10000
        # SMA strategy
        self.backtrack_sma()
        # All in strategy
        self.backtrack_all_in()
        # Automatic Strategy
        self.backtrack_automatic()
        period_invest_fund = initial_balance/12
        idx =[i for i in range(4,close_prices.shape[0],int(close_prices.shape[0]/12+1))]
        shares = sum(period_invest_fund/close_prices[idx])
        total_asset = shares*close_prices[-1]
        performance = total_asset/initial_balance - 1
        results['Automatic_Monthly'] = "{0} final total assets: {3:.2f} $ performance: {4:.1%} {1:.1f} shares @price:{2:.2f} $".format(stock_token,shares,close_prices[-1],total_asset, performance)
        
       
        return results



def main():
    watch_list=["SPY","AAPL"]
    # watch_list = ["AAPL","ADBE","AMD","AMZN","ARKK","ATVI","BABA","BIDU","BILI",
    #               "CRM","DIDIY","DIS","DOCU","EA","EDU","ENPH","FDX","GILD",
    #               "GOOG","HUYA","IAU","JD","JNJ","MA","META","MSFT","MU","NFLX",
    #               "NIO","NTES","NVDA","PARA","PDD","PFSI","PINS","PYPL","QQQ",
    #               "SNAP","SPY","T","TAL","TCEHY","TME","TSLA","TWLO","U","UBER",
    #               "V","VRTX","VXX","VZ","WMT","ZM"]
    sr = StockRadar(watch_list)
    backtrack = sr.backtrack()
    sma = sr.checkSMACrossing()
    
    
    data = yf.download("SPY AAPL", start="2017-01-01", end="2017-04-30")
    apple = data["Close"]["AAPL"]
    msft = yf.Ticker("MSFT")
    # get stock info
    info=msft.info
    
    # get historical market data
    hist = msft.history(period="max")
    
    # show actions (dividends, splits)
    actions = msft.actions
    
    # show sustainability
    sustainability= msft.sustainability
    
    # show analysts recommendations
    recommendations = msft.recommendations
    
    # show news
    news = msft.news
    
    a = 0
    return


if __name__ == '__main__':
    main()