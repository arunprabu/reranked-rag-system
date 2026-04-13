# RAG Evaluation Queries (HR Policies 2025 vs 2026)

## 🔍 Version Comparison Queries

- What changed in maternity leave policy from 2025 to 2026?
- Compare salary payment timelines between 2025 and 2026
- What are the differences in reimbursement processing time?
- How has the work-from-home policy changed in 2026?
- Compare onboarding process in 2025 vs 2026
- What improvements were made in HR support channels in 2026?
- Compare notice period policy between 2025 and 2026
- What changed in employee benefits in 2026?
- Compare tax handling approach in 2025 vs 2026
- What are the differences in attendance correction process?

---

## 🆕 Latest Policy Queries

- What is the latest leave policy?
- What is the current salary credit date?
- What is the latest reimbursement processing time?
- What is the updated work-from-home policy?
- What is the current notice period?
- What is the latest onboarding process?
- What is the current HR helpdesk timing?
- What is the latest policy for salary advances?
- What is the updated insurance enrollment process?
- What is the current leave approval process?

---

## 🔀 Cross-Document Reasoning Queries

- What improved in HR operations from 2025 to 2026?
- Which policies became faster in 2026?
- What processes are now automated in 2026?
- What new features were added to the HR portal?
- How did employee benefits evolve from 2025 to 2026?
- What changes were made to payroll processing?
- What policies became more flexible in 2026?
- Which areas saw the most improvement in employee experience?
- What are the key differences in support channels between years?
- What changed in grievance handling?

---

## 🛒 Product Queries (NL2SQL — `products` + `categories`)

- What are the top 5 most expensive products?
- Show me all Electronics products under $100
- List all products in the Sports & Outdoors category
- Which products are currently out of stock or inactive?
- Give me details of the wireless headphones
- What is the price of the LEGO Technic Bugatti Chiron?
- Show me all books and their prices
- Which products have a stock quantity below 50?
- List all products in the Clothing category
- What are the cheapest products available?
- Show me all Health & Beauty products
- Which is the most affordable item in the Electronics category?
- List all Home & Kitchen products priced above $100
- What products are available in the Toys & Games category?
- Show me all products with "organic" in the name

---

## 📦 Order Queries (NL2SQL — `orders` + `order_items`)

- How many orders are in shipped status?
- List all delivered orders
- Which orders are still pending?
- What is the total revenue from all delivered orders?
- Show me orders placed in the last 7 days
- Which customer placed the highest value order?
- How many orders have been cancelled?
- List all confirmed orders with their total amounts
- What is the average order value?
- How many orders are there per status?
- Which customer ordered the most recently?
- Show me all orders above $300
- What is the total number of orders placed?
- List orders placed in the last 30 days
- Which orders contain Electronics products?

---

## 🔗 Cross-Table Product + Order Queries (NL2SQL — joins)

- Which products have been ordered the most?
- What is the total quantity sold for each product?
- Which category generates the most revenue?
- Show me the top 3 best-selling products by quantity
- What products did Alice Johnson order?
- Which customers ordered books?
- What is the total sales revenue by category?
- How many units of headphones have been sold across all orders?
- Which products have never been ordered?
- Show me all products ordered by customers with delivered status

---

## ⚠️ Ambiguous Queries

- What is the leave policy?
- How do I apply for leave?
- What is the reimbursement time?
- When will I get my salary?
- How do I contact HR?
- What is the onboarding process?
- What is the notice period?
- How do I claim benefits?
- What is the attendance correction process?
- How do I resign?

---

## 🧪 Edge / Stress Test Queries

- Give me only the latest policy details
- Ignore old policies and tell me current rules
- What changed recently in HR policies?
- Show me outdated vs current policy differences
- Which policy is no longer valid in 2026?
- What policies were updated recently?
- Give me a summary of all changes in 2026
- Which policies remained unchanged?
- What policies improved in speed or automation?
- Compare old vs new HR system features
