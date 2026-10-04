-- Runs once, when the Postgres volume is first created.
create extension if not exists vector;
create schema if not exists serving;
