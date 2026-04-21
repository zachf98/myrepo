function EventSelector({
  events,
  selectedEventUrl,
  onEventChange,
  selectedEvent,
  loading,
}) {
  return (
    <div className="event-selector">
      <label htmlFor="event-dropdown">Select UFC Event</label>
      <select
        id="event-dropdown"
        value={selectedEventUrl}
        onChange={(event) => onEventChange(event.target.value)}
        disabled={loading || !events.length}
      >
        {loading ? <option>Loading events...</option> : null}
        {!loading && !events.length ? <option>No events found</option> : null}
        {events.map((event) => (
          <option key={event.id} value={event.eventUrl}>
            [{event.category}] {event.name} — {event.date}
          </option>
        ))}
      </select>
      {selectedEvent ? (
        <p className="event-meta">
          <strong>{selectedEvent.name}</strong>
          <br />
          {selectedEvent.date} · {selectedEvent.location}
        </p>
      ) : null}
    </div>
  );
}

export default EventSelector;
