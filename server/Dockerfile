# bgtracker aggregator - stdlib only, so the image is tiny and has zero pip deps.
# Same image runs both roles; docker-compose picks the command per service.
#
# The build context is the REPO ROOT, not server/ (see docker-compose.yml), so
# the aggregator can import the client's own archetype definitions. Comps are
# labelled with bgtracker.COMP_FAMILIES and data/comp_roles.json rather than a
# second list written here - a copy would drift, and the feed and the panels
# would then disagree about what an archetype is. aggregate.py degrades
# honestly when they are missing (the comps file says the classifier was
# unavailable and carries no rows), so an older deploy shape still runs; it
# just cannot rank comps.
FROM python:3.12-slim

RUN useradd -m -u 10001 app
WORKDIR /app
COPY server/ingest.py server/aggregate.py server/tips.py ./
COPY bgtracker.py paths.py ./
# comp_roles.json: what makes a minion core to an archetype, for aggregate.py.
# hero_tips.json: the lines that SHIP with the client, which tips.py --seed puts
# in the table so the vote is not unopposed - people have to be able to rank the
# line already on their screen against the ones being proposed, or the only
# thing on the ballot is other people's submissions.
COPY data/comp_roles.json data/hero_tips.json data/
# The card pool (names, tribes, card text) is fetched once a day and cached
# here. Owned by the app user, because the container does not run as root.
RUN mkdir -p /app/.cache && chown -R app:app /app/.cache

USER app
# Overridden by docker-compose for the aggregate and tips services.
CMD ["python", "ingest.py"]
