""" @author Cedric Walker
LPS/t statistics from PS project database

requirements
pandas                        1.3.5
matplotlib                    3.3.2
numpy                         1.21.6
""""

import sqlite3
from pandas import Timestamp
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime

out_name = 'ps_interval_measurments'
db_path = 'patch_sorter_data.db'
con = sqlite3.connect(db_path)  # open PS instance database
n=16158  # number of objects in project.

df_j = pd.read_sql("select *  from project", con=con)  # list all projects in PS insatance
id = 47  # project number

# list and count all dl and embedding related jobs
df_job = pd.read_sql(f"select * from job where projId=={id} and cmd!='make_patches' and status=='DONE'", con=con)
sub_df = df_job.iloc[3:]  # do not count initial embedding and setup time.

# print computer time
print((pd.to_datetime(sub_df['end_date']) - pd.to_datetime(sub_df['start_date'])).sum())

# PS saves number of labeled objects to db with timestamp.
df_j = pd.read_sql(f"select * from metrics where projID=={id}", con=con)

# check if measurments where done on different days.
df_j['day'] = df_j['label_update_time'].str.extract('(\d\d\d\d-\d\d-\d\d)')
days=np.unique(df_j['day']).tolist()

# define video intervalls to measure.
l = []
## go through measurments day by day
for date in days:
    df_j_1 = pd.read_sql(f"select * from metrics where projID=={id} and label_update_time LIKE '%{date}%'", con=con)
    tmp = df_j_1.set_index(pd.DatetimeIndex( df_j_1['label_update_time'])).resample('5T').sum()  # measure in 5 minute intervalls
    tmp.resample('5T').sum()
    tmp['s'] = tmp['no_of_objects_labelled']/300  (300 seconds per 5 mins for lps measurment)
    tmp.reset_index().plot.bar(x='label_update_time', y='s')
    l.append(tmp[tmp['s']!=0])

f, ax = plt.subplots(1,1)
s = pd.concat(l).reset_index().reset_index().plot.bar(x='index', y='s', ax = ax)
ax.get_figure().savefig('barplot.png', dpi=500)
pd.concat(l).reset_index().reset_index().to_excel(f'{out_name}.xlsx')
