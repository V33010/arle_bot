# contains sql to create the database schema
c_users_tbl = """
create table users (
  id integer primary key autoincrement,
  username text not null unique,
  created_at datetime default current_timestamp
);
"""

c_acc_tbl = """
create table accounts (
  id integer primary key autoincrement,
  user_id integer not null,
  account_name text,
  created_at datetime default current_timestamp,
  riot_id text not null unique,
  foreign key (user_id) references users (id)
);
"""

c_skins_tbl = """
create table skins (
  id integer primary key autoincrement,
  name text not null unique,
  pickrate real default 0.0,
  total_occurrence_rate real default 0.0
);
"""

c_acc_skins_tbl = """
create table account_skins (
  account_id integer not null,
  skin_id integer not null,
  primary key (account_id, skin_id),
  foreign key (account_id) references accounts (id),
  foreign key (skin_id) references skins (id)
);
"""

c_crosshairs_tbl = """
create table crosshairs (
  id integer primary key autoincrement,
  crosshair_code text not null unique
);
"""

c_acc_crosshair_tbl = """
create table account_crosshairs (
  account_id integer not null,
  crosshair_id integer not null,
  primary key (account_id, crosshair_id),
  foreign key (account_id) references accounts (id),
  foreign key (crosshair_id) references crosshairs (id)
);
"""
