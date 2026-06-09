# Tearsheet
 
A multi-agent system that generates verified, sourced company due-diligence briefs.
 
Given a company, Tearsheet plans the research, gathers data across financial sources (market data, filings, news), verifies it against the source, and produces a structured brief with citations for its claims.
 
It is a research and analysis tool — it surfaces verified facts and does not provide investment advice.
 
> 🚧 **Work in progress.** Early development — architecture and details will evolve.
 
## Tech stack
 
Python, LangGraph (multi-agent orchestration), Claude / GPT, MCP for tools, yfinance + SEC EDGAR + news API for data, PostgreSQL + pgvector for storage, FastAPI backend.
 
## Status
 
Currently setting up the project and building the evaluation benchmark. More to come.
