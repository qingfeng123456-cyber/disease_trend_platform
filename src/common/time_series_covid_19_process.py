import pandas as pd
texts = ['confirmed', 'deaths', 'recovered']
for text in texts:
    try:
        df = pd.read_csv(f'../../data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/time_series_covid_19_{text}.csv',encoding='utf-8')

        drop_cols = ['Lat','Long','Province/State']

        df = df.drop(columns=drop_cols, errors='ignore')
        key_col = ['Country/Region']
        result = df.groupby(key_col, as_index=False).sum(numeric_only=True)
        result.to_csv(f'../../data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/time_series_covid_19_{text}_combined.csv', index=False, encoding='utf-8')
    except Exception as e:
        print(e)