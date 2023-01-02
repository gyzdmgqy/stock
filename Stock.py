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
    def __init__(self, watch_list, backtrack_output):
        self.watch_list = watch_list
        self.data = None
        self.sma = None
        self.backtrack_list = []
        self.transactions = []
        self.backtrack_output = backtrack_output
        
    def __load_data(self):
        watch_list_string = " ".join(self.watch_list)
        self.data = yf.download(watch_list_string, start="2020-01-01")
        return
    
    def getMovingAverage(self):
        if not self.data:
            self.__load_data()
        self.sma_window_sizes = [5,10,20,30,50,100,200]
        self.sma_tokens = ["SMA{}".format(window_size) for window_size in self.sma_window_sizes]
        #self.sma = self.data.loc[:,(["Close"],self.watch_list)]
        columns = pd.MultiIndex.from_product([self.sma_tokens, self.watch_list], names=['sma_type','token'])
        self.sma = pd.DataFrame(columns = columns)
        for window_size in self.sma_window_sizes:
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
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            initial_balance = 10000
            # SMA strategy
            for window_size in self.sma_window_sizes:
                sma_token = "SMA{}".format(window_size)
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
                        if window_size>=100 and close_today > sma_today:
                            shares_to_buy = initial_balance/close_prices[row]
                            shares += shares_to_buy
                            balance = 0
                            total_asset = shares*close_prices[row]+balance
                            self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'buy',shares_to_buy,close_today,
                                                      balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])                    
                        else:
                            balance += initial_balance
                        year_start_asset = shares*close_prices[row] + balance
                    if close_today > sma_today and close_yesterday < sma_yesterday:
                        if balance > 0:
                            shares_to_buy = balance/close_today
                            shares += shares_to_buy
                            total_asset = shares*close_today
                            balance = 0
                            self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'buy',shares_to_buy,close_today,
                                                      balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])                    
                    elif close_today < sma_today and close_yesterday > sma_yesterday:
                        if shares>0:
                            shares_to_sell = shares
                            balance_credits = shares*close_today
                            shares =0
                            balance+=balance_credits
                            total_asset = balance
                            self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'sell',shares_to_sell,close_today,
                                                      balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])  
                    if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                        total_asset = shares*close_prices[row]+balance
                        performance = total_asset/year_start_asset - 1
                        self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'hold',shares,close_prices[row],
                                                      balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])
                        self.backtrack_list.append([stock_token,sma_token,year,performance])   
                        next_year = True
        return
    
    def backtrack_all_in(self):
        sma_token = 'All_In'
        initial_balance = 10000
        for stock_token in self.watch_list:
            close_prices = self.data["Close"][stock_token]
            shares = 0
            balance = initial_balance
            for row in range(close_prices.shape[0]):
                if shares == 0:
                    shares = balance/close_prices[row]
                    year = close_prices.index[row].year
                    self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'buy',shares,close_prices[row],
                                                      0,balance,close_prices.index[row].strftime("%Y-%m-%d")])
                    balance = 0
                if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                    total_asset = shares*close_prices[row]+balance
                    performance = total_asset/initial_balance - 1
                    self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'hold',shares,close_prices[row],
                                                      balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])
                    self.backtrack_list.append([stock_token,sma_token,year,performance])   
                    shares = 0
                    balance = initial_balance
        return
                
    def backtrack_automatic(self):
        sma_tokens = [('Automatic_Daily',0),('Automatic_Monthly',12),('Automatic_Biweekly',24)]
        initial_balance = 10000
        for sma_token,frequency in sma_tokens:
            for stock_token in self.watch_list:
                close_prices = self.data["Close"][stock_token]
                shares = 0
                next_year = True
                for row in range(close_prices.shape[0]):
                    if next_year:
                        year = close_prices.index[row].year
                        next_year = False
                        ndays = len(close_prices[close_prices.index.year == year])
                        n_interval = ndays if frequency == 0 else frequency
                        period = ndays//n_interval
                        balance = initial_balance
                        periodic_invest_fund = initial_balance/n_interval
                        year_start_asset = shares*close_prices[row] + balance
                    if row % period == 0 and balance*1.1>=periodic_invest_fund:
                        new_shares=periodic_invest_fund/close_prices[row]
                        shares+=new_shares
                        balance-=periodic_invest_fund
                        total_asset = shares*close_prices[row] + balance
                        self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'buy',new_shares,close_prices[row],
                                                              balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])
                    if row == close_prices.shape[0]-1 or close_prices.index[row+1].year>year:
                        total_asset = shares*close_prices[row] + balance
                        performance = total_asset/year_start_asset - 1
                        self.transactions.append([sma_token,stock_token,close_prices.index[row].year,'hold',new_shares,close_prices[row],
                                                          balance,total_asset,close_prices.index[row].strftime("%Y-%m-%d")])
                        self.backtrack_list.append([stock_token,sma_token,year,performance])   
                        next_year = True
        return
    
    def backtrack(self):
        # SMA strategy
        self.backtrack_sma()
        # All in strategy
        self.backtrack_all_in()
        # Automatic Strategy
        self.backtrack_automatic()
        backtrack_df = pd.DataFrame(data=self.backtrack_list,columns = ['Stock','Strategy','Year','Performance'])
        backtrack_df.to_csv(self.backtrack_output+'performance.csv')
        transaction_df = pd.DataFrame(data=self.transactions,columns = ['Strategy','Stock','Year','Transaction','Shares','Price',
                                                              'Balance','Total Asset','Date'])
        transaction_df.to_csv(self.backtrack_output+'transaction.csv')

        return



def main():
    watch_list=["SPY","AAPL"]
    # watch_list = ["AAPL","ADBE","AMD","AMZN","ARKK","ATVI","BABA","BIDU","BILI",
    #               "CRM","DIDIY","DIS","DOCU","EA","EDU","ENPH","FDX","GILD",
    #               "GOOG","HUYA","IAU","JD","JNJ","MA","META","MSFT","MU","NFLX",
    #               "NIO","NTES","NVDA","PARA","PDD","PFSI","PINS","PYPL","QQQ",
    #               "SNAP","SPY","T","TAL","TCEHY","TME","TSLA","TWLO","U","UBER",
    #               "V","VRTX","VXX","VZ","WMT","ZM"]
    sr = StockRadar(watch_list,r"C:\\Dropbox\\Share for Gary\\Investment\\")
    sr.backtrack()
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