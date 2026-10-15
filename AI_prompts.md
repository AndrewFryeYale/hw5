# AI Prompts — HW5

## Setup

1. Today we will be completing hw5 please create a hw5 folder set the wd to that folder and start logging prompts like you have for other hw

## Problem 1

1. Problem 1: Context today we will be designing a multi agent system that runs our campus group shop, the system will have full connectivity between the 5 agents: boss, inventory, accounting, facilities, and customer service. The data lives in data.zip which you should unzip now. As always do not work ahead and log every prompt, for problem 1 only unzip the data

2. It was already unzipped my bad.

## Problem 2

1. Problem 2: Open data/campus_customs.db look through every field and copy the file to campus_customs_new.db later problems will update that copy. Study the three open tickets and how they relate to other tables. Start output/harness.md and for each table and for each table list the fields and a short line about why that table matters for the agents, the harness will continue to grow as we go

## Problem 3

1. Problem 3: write an MCP server in mcp_server using FastMCP it will talk to data/campus_customs_new.db and you do not need to connect or run it in this problem. Every agent in this hw will use this MCP server for now write three tools for the server that you know you will need for the tickets. Keep the names clear, never invent data, and only use info from the db. In output/harness list each tool and include a description describing which ticket that tool will help address and why it is the right tool for that ticket

## Problem 4

1. Problem 4: Add the MCP server to this project now and save the connection in json text in .mcp.json at the project root. Make sure you (the vibe coder) are connected to the mcp server. Save the evidence in output/mcp_smoke.json. Then test the MCP server and for each tool ask it a prompt recording the tool name, the prompt, and the output. Which must match the values in data/campus_customs_new.db

## Problem 5

1. Problem 5: Build the agentic team for campus customs using pydanticai: Boss, Inventory, Accounting, Facilities, and Customer Service (use luna to save on token cost). Include prompts, models, and agent loops so the team work effectively and delegate work to each other for full connectivity. Put agent prompts in backend/prompts/ one file per agent. Put data types in backend/models.py and the agent files under backend/ make prompts detailed that cover all aspects of the agents work. Add any other tools needed for the agents to work on the ticket work. Shop facts come from the MCP server only. Wire the agents so they append and audit to output/audit_trail.json as they run. In output/harness.md list each agent and tool along with the tables used. Also add guardrails section that the real business would want when using agents to keep in touch with real customers and also how to be effecient with token use. ALso update mcp_server/READ.me so the tools match

## Problem 6

1. Problem 6: before you wire the backend write what you expect the team to do on each ticket to do. Then create output/desk_tickets.html a page I can double click with one tab per ticket, and a tab for cash and a tab for reflections (we will work on those later). On each ticket tab fill in your expectation - leaving room for actual which we will work on later. In expectations write who you think the boss will call first, all the agent delegations you expect, and which mcp tools you expect to be used. Also give me instructions on how to write over this as I will manually write over this later. Also plans that send every specialist on every ticket score low, efficiency is key.

## Problem 7

1. Problem 7: in backend/main.py use FastAPI and add routes that do the following: - return the three tickets and whether each is open or resolved, - take a ticket id and run your agent on that ticket, - return recent agent events (what each agent said and what tools they used) so the board can refresh, - approve a payment or purchase after a human clicks approve, - return the current checking balance from cash_accounts, - reset the database to original values when we want to try a fresh run. From the backend folder start the server with uvicorn main:app --reload --port 8000. In output/harness.md list each route in one line

## Problem 8

1. Problem 8: now we will build the front end, in frontend/ build the dashboard using react + vite + typescript. The board should list all tickets, let the user pick one ticket and start the agent team on it, show each agent and what they are saying/ doing on while running, market a ticket resolved when it has been resolved, show a short summary of what each agent did on the ticket after, let a human approve a payment or purchase when asked, show the checking balance. Make the dashboard look good and presentable, someone should want to sit at this desk and use this dashboard. Tell the front end to talk to the backend at localhost8000 on the backend allow the vite page origin. The dashboard should run from npm run dev. Write output/design.md with your design choices and why you made them. Also add at least one truly unique design aspect to the dashboard.

## Problem 9

1. Problem 9: before testing the agents reset the campus_customs_new.db. Then run all three tickets until each is resolved. Open the output/desk_tickets.html from problem 6 and write the actual section for each ticket: which agents worked, what they delegated, and which tools they used. Make sure to keep the expected section for comparison. On the cash tab itemize the money starting checking balance (after the reset), for each ticket how cash was changed, and ending balance (matching the cash_account balance in the db) wrong cash math loses points even if every ticket is resolved so be extra careful there. Also save output/resolved_tickets.json for each ticket: id, final status, short outcome, what each agent contributed, and any human approvals. And output/resolved_board.html with screenshots of the final react board for each resolves ticket. Append real runs to output/audit_trail.json and finish output/harness.md to include tables, mcp servers, api routes, agents, dashboard, and rules.

## Problem 10

1. Problem 10: Open output/desk_tickets.html, in the reflections tabs answer in my vibe how you would evaluate the performance of each agent and why? For each ticket how did the actual compare to the expected? What would have been simpler as one agent with tools and why? Describe three new problems Campus Customs might face that this agent team could answer with the built tools? Describe three new problems that Campus Customs might face that this team could not solve? Tie every answer to the app we just built and use the ticket tabs and cash tabs as evidence supporting your answers. Make sure to include details about the case and Campus Customs in the reflection. ALso again note that i will be manually editing this
