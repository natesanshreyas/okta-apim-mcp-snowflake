-- Sample dataset served by the mock Snowflake backend (mcp-server/snowflake_client.py).
-- This mirrors what the MockBackend returns, and is the DDL you would run in a
-- REAL Snowflake account (SNOWFLAKE_MODE=real) to reproduce the demo.

CREATE DATABASE IF NOT EXISTS MCP_DEMO_DB;
CREATE SCHEMA   IF NOT EXISTS MCP_DEMO_DB.PUBLIC;

USE DATABASE MCP_DEMO_DB;
USE SCHEMA PUBLIC;

CREATE OR REPLACE TABLE CUSTOMERS (
    CUSTOMER_ID NUMBER,
    NAME        VARCHAR,
    REGION      VARCHAR,
    SIGNUP_DATE DATE
);

INSERT INTO CUSTOMERS VALUES
    (1, 'Acme Corp', 'AMER', '2023-01-15'),
    (2, 'Globex',    'EMEA', '2023-03-02'),
    (3, 'Initech',   'AMER', '2023-06-21'),
    (4, 'Umbrella',  'APAC', '2024-02-10');

CREATE OR REPLACE TABLE ORDERS (
    ORDER_ID    NUMBER,
    CUSTOMER_ID NUMBER,
    AMOUNT      NUMBER,
    ORDER_DATE  DATE
);

INSERT INTO ORDERS VALUES
    (1001, 1, 2500, '2024-05-01'),
    (1002, 2, 1800, '2024-05-03'),
    (1003, 1, 3200, '2024-06-12'),
    (1004, 3,  900, '2024-06-15'),
    (1005, 4, 4100, '2024-07-01');
