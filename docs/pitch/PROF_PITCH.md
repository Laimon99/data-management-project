Dear Professor ____,
We would like to ask for your feedback on a possible topic for our Data Management project.

We are considering analysing restaurant reviews in the Milan area, focusing on how ratings differ across platforms (e.g. Google Maps, TheFork, TripAdvisor). The goal is to study consistency between platforms and understand whether differences are related to data quality issues.

Questions that this project may help us answer may be:

1. How consistent are restaurant ratings across different online platforms?
2. Which restaurants show the highest disagreement between platforms?
3. Is rating inconsistency related to data quality issues (e.g. number of reviews, missing fields, outdated information)?
4. Can low-quality or sparse data inflate perceived restaurant quality?
5. Are certain platforms systematically more optimistic/pessimistic?
6. Does inconsistency increase for smaller or less popular restaurants?
7. Does geographic location (centre vs periphery) matter for quality?

Data sources and acquisition:

* Google Places API (plus possibly additional APIs)
* Web scraping from TheFork and TripAdvisor

Tools and approach:

* Python for API calls
* Scraping via Selenium/Playwright or BeautifulSoup (also, we are interested in exploring an agentic approach using* tools such as Firecrawl)
* Filtering noisy or incorrect venues (e.g. misclassified places) using LLMs
* Record linkage to match restaurants across platforms
* Document-based database for restaurants/bars and text reviews
* Optionally use models to extract features from the comments

Would this topic and scope be appropriate for the project? We estimate collecting a few thousand records for the venues (depending on availability on the platforms - 1-3k samples), would this data volume be sufficient?

Thank you in advance for your feedback.

Best regards,
___