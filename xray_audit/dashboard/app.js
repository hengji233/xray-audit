async function getJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return await resp.json();
}

function setRows(tableId, rowsHtml) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.innerHTML = rowsHtml.join("\n");
}

function safe(v) {
  return (v ?? "").toString().replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

async function refresh() {
  try {
    const [health, domains, users, events] = await Promise.all([
      getJSON('/api/v1/health'),
      getJSON('/api/v1/domains/top?window=5m&limit=20'),
      getJSON('/api/v1/users/active?seconds=30&limit=20'),
      getJSON('/api/v1/events/recent?seconds=10&limit=50')
    ]);

    const dbState = health.db_state || {};
    document.getElementById('health').textContent =
      `node=${safe(health.node_id)} offset=${safe(dbState.last_offset || 0)} updated_at=${safe(dbState.updated_at || '-')}`;

    setRows('domains-table', domains.items.map(item =>
      `<tr><td>${safe(item.domain)}</td><td>${safe(item.hits)}</td></tr>`
    ));

    setRows('users-table', users.items.map(item =>
      `<tr><td>${safe(item.user_email)}</td><td>${safe(item.last_seen_unix)}</td></tr>`
    ));

    setRows('events-table', events.items.map(item =>
      `<tr>
        <td>${safe(item.event_time)}</td>
        <td>${safe(item.event_type)}</td>
        <td>${safe(item.user_email || '-')}</td>
        <td>${safe(item.dest_host || item.dest_raw || item.domain || '-')}</td>
        <td>${safe(item.status || item.dns_status || '-')}</td>
        <td>${safe(item.raw_line)}</td>
      </tr>`
    ));
  } catch (err) {
    document.getElementById('health').textContent = `error: ${err}`;
  }
}

refresh();
setInterval(refresh, 3000);
