import pandas as pd
texts = ['confirmed', 'deaths', 'recovered']
for text in texts:
    try:
        inp = f'../../data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/time_series_covid_19_{text}_combined.csv'
        out = f'../../data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/time_series_covid_19_{text}_daily.csv'

        df = pd.read_csv(inp, encoding="utf-8")

        key_col = "Country/Region"
        date_cols = [c for c in df.columns if c != key_col]

        daily = df.copy()
        daily[date_cols] = daily[date_cols].diff(axis=1)

        daily[date_cols[0]] = df[date_cols[0]]

        daily[date_cols] = daily[date_cols].clip(lower=0)

        daily.to_csv(out, index=False, encoding="utf-8")
        print("saved:", out)
    except Exception as e:
        print(e)