export interface Env { DB: D1Database; GATEWAY_TOKEN: string }
type Input = Record<string, unknown>
const MAX = { page: 5000, limit: 5000, batch: 100, ingestBatch: 50 }
const canonicalDate = (date: Date) => date.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z")
const now = () => canonicalDate(new Date())
const ago = (amount: number, unit: "seconds" | "hours" | "days") => {
  const multiplier = unit === "seconds" ? 1000 : unit === "hours" ? 3600000 : 86400000
  return canonicalDate(new Date(Date.now() - amount * multiplier))
}
const str = (v: unknown, name: string, max = 1000) => { if (typeof v !== "string" || v.length > max) throw new Bad("INVALID_INPUT", `${name} must be a string of at most ${max} characters`); return v }
const reqStr = (o: Input, n: string, max = 1000) => { const v = str(o[n], n, max); if (!v) throw new Bad("INVALID_INPUT", `${n} is required`); return v }
const num = (v: unknown, n: string, min = 0, max = 2147483647) => { if (typeof v !== "number" || !Number.isInteger(v) || v < min || v > max) throw new Bad("INVALID_INPUT", `${n} must be an integer between ${min} and ${max}`); return v }
const safeInt = (v: unknown, n: string) => num(v, n, 0, Number.MAX_SAFE_INTEGER)
const int64 = (v: unknown, n: string, nullable = false) => {
  if (nullable && (v === null || v === undefined)) return null
  const raw = typeof v === "number" && Number.isSafeInteger(v) ? String(v) : v
  if (typeof raw !== "string" || !/^-?\d+$/.test(raw)) throw new Bad("INVALID_INPUT", `${n} must be a signed 64-bit decimal string`)
  const value = BigInt(raw)
  if (value < -9223372036854775808n || value > 9223372036854775807n) throw new Bad("INVALID_INPUT", `${n} is outside the signed 64-bit range`)
  return raw
}
const text = (v: unknown, n: string) => str(v, n, 100000)
const limit = (v: unknown, fallback = 50) => Math.min(MAX.limit, Math.max(1, typeof v === "number" && Number.isInteger(v) ? v : fallback))
const page = (o: Input) => { const p = num(o.page ?? 1, "page", 1, 1000000); const size = Math.min(MAX.page, limit(o.page_size, 50)); return { p, size, offset: (p - 1) * size } }
const iso = (v: unknown, n: string) => { const s = reqStr({ [n]: v }, n, 64); const d = new Date(s); if (Number.isNaN(d.valueOf())) throw new Bad("INVALID_INPUT", `${n} must be an ISO timestamp`); const utc = s.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$/); return utc ? `${utc[1]}.${(utc[2] ?? "").padEnd(6, "0")}Z` : canonicalDate(d) }
const json = (v: unknown, n: string) => { try { return JSON.stringify(v ?? null) } catch { throw new Bad("INVALID_INPUT", `${n} must be JSON serializable`) } }
class Bad extends Error { constructor(public code: string, message: string, public retryable = false) { super(message) } }
const ok = (data: unknown) => Response.json({ ok: true, data })
const fail = (e: unknown) => { const x = e instanceof Bad ? e : new Bad("INTERNAL_ERROR", "storage operation failed", true); return Response.json({ ok: false, error: { code: x.code, message: x.message, retryable: x.retryable } }, { status: x.code === "UNAUTHORIZED" ? 401 : x.code === "INVALID_INPUT" ? 400 : x.code === "NOT_FOUND" ? 404 : 500 }) }
const all = async (db: D1Database, sql: string, ...args: unknown[]) => (await db.prepare(sql).bind(...args).all<Record<string, any>>()).results
const first = async (db: D1Database, sql: string, ...args: unknown[]) => (await db.prepare(sql).bind(...args).first<Record<string, any>>())
const write = (db: D1Database, sql: string, ...args: unknown[]) => db.prepare(sql).bind(...args)
const range = (o: Input) => ({ from: iso(o.from, "from"), to: iso(o.to, "to") })
const paged = async (db: D1Database, sql: string, countSql: string, args: unknown[], offset: number, size: number) => ({ total: Number((await first(db, countSql, ...args))?.total ?? 0), items: await all(db, `${sql} LIMIT ? OFFSET ?`, ...args, size, offset) })

async function ingest(db: D1Database, events: unknown[], node: string) {
  if (!Array.isArray(events) || events.length > MAX.ingestBatch) throw new Bad("INVALID_INPUT", "events must contain at most 50 items")
  const statements: D1PreparedStatement[] = []
  for (const raw of events) {
    const e = raw as Input; if (!e || typeof e !== "object") throw new Bad("INVALID_INPUT", "event must be an object")
    if (!e.access) continue
    const t = iso(e.event_time, "event_time"); const hash = reqStr({ event_hash: e.event_hash ?? e.raw_hash }, "event_hash", 64); const a = e.access as Input
    const destRaw = str(a.dest_raw,"dest_raw",512) ?? ""; const protocol = str(a.protocol ?? (destRaw.startsWith("tcp:") ? "tcp" : destRaw.startsWith("udp:") ? "udp" : ""),"protocol",32) ?? ""
    statements.push(write(db, `INSERT INTO audit_access_events(event_time,user_email,src,dest_host,dest_port,protocol,status,detour,reason,is_domain,node_id,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_hash,event_time,node_id) DO UPDATE SET user_email=excluded.user_email,src=excluded.src,dest_host=excluded.dest_host,dest_port=excluded.dest_port,protocol=excluded.protocol,status=excluded.status,detour=excluded.detour,reason=excluded.reason,is_domain=excluded.is_domain`, t, str(a.user_email,"user_email",191) ?? "", str(a.src,"src",255) ?? "", str(a.dest_host,"dest_host",191) ?? "", a.dest_port ?? null, protocol, str(a.status,"status",32) ?? "", str(a.detour,"detour",255) ?? "", text(a.reason,"reason") ?? "", a.is_domain ? 1 : 0, node, hash))
  }
  if (statements.length) await db.batch(statements); return { count: statements.length }
}

async function operation(db: D1Database, name: string, o: Input): Promise<unknown> {
  switch (name) {
    case "load_state": case "collector_state": return await first(db, "SELECT file_path,CAST(inode AS TEXT) inode,CAST(last_offset AS TEXT) last_offset,updated_at FROM collector_state WHERE file_path=?", reqStr(o,"file_path",255))
    case "save_state": return await db.batch([write(db,"INSERT INTO collector_state(file_path,inode,last_offset,updated_at) VALUES(?,?,?,?) ON CONFLICT(file_path) DO UPDATE SET inode=excluded.inode,last_offset=excluded.last_offset,updated_at=excluded.updated_at", reqStr(o,"file_path",255), int64(o.inode,"inode",true), int64(o.offset,"offset"), now())]).then(() => ({ saved: true }))
    case "ingest_events": return ingest(db, o.events as unknown[], reqStr(o,"node_id",32))
    case "prune_old_events": { const days = num(o.retention_days,"retention_days",1,36500), size = num(o.delete_batch_size,"delete_batch_size",1,500), threshold = ago(days, "days"); const r = await db.prepare("DELETE FROM audit_access_events WHERE id IN (SELECT id FROM audit_access_events WHERE event_time < ? ORDER BY id LIMIT ?)").bind(threshold,size).run(); return { deleted: r.meta.changes ?? 0 } }
    case "admin_user_count": return { count: Number((await first(db,"SELECT COUNT(*) AS total FROM audit_admin_users"))?.total ?? 0) }
    case "admin_user_get": return first(db,"SELECT id,username,password_hash,token_version,is_enabled,must_change_password,last_login_at,created_at,updated_at FROM audit_admin_users WHERE username=?",reqStr(o,"username",64))
    case "admin_user_create": { const t=now(); await db.batch([write(db,"INSERT INTO audit_admin_users(username,password_hash,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?)",reqStr(o,"username",64),reqStr(o,"password_hash",255),o.must_change_password?1:0,t,t)]); return { created:true } }
    case "admin_user_update_login_success": return db.prepare("UPDATE audit_admin_users SET last_login_at=?,updated_at=? WHERE username=?").bind(now(),now(),reqStr(o,"username",64)).run()
    case "admin_user_bump_token_version": return db.prepare("UPDATE audit_admin_users SET token_version=token_version+1,updated_at=? WHERE username=?").bind(now(),reqStr(o,"username",64)).run()
    case "admin_user_change_password": return db.prepare("UPDATE audit_admin_users SET password_hash=?,token_version=token_version+1,must_change_password=0,updated_at=? WHERE username=?").bind(reqStr(o,"new_password_hash",255),now(),reqStr(o,"username",64)).run()
    case "auth_event_insert": return db.prepare("INSERT INTO audit_auth_events(event_type,username,source_ip,user_agent,event_time) VALUES(?,?,?,?,?)").bind(reqStr(o,"event_type",32),reqStr(o,"username",64),str(o.source_ip,"source_ip",64)??"",str(o.user_agent,"user_agent",500)??"",now()).run()
    case "runtime_config_all": return all(db,"SELECT config_key,value_json,value_type,scope,updated_by,updated_at FROM audit_runtime_config ORDER BY config_key")
    case "runtime_config_upsert": { const items=o.items; if (!items || typeof items !== "object" || Array.isArray(items)) throw new Bad("INVALID_INPUT","items must be an object"); const entries=Object.entries(items); if(!entries.length)return {updated:0}; const t=now(), s:D1PreparedStatement[]=[]; for(const [key,value] of entries) { const old=await first(db,"SELECT value_json FROM audit_runtime_config WHERE config_key=?",key); const v=json(value,"value"); s.push(write(db,"INSERT INTO audit_runtime_config(config_key,value_json,value_type,scope,updated_by,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(config_key) DO UPDATE SET value_json=excluded.value_json,value_type=excluded.value_type,updated_by=excluded.updated_by,updated_at=excluded.updated_at",key,v,Array.isArray(value)?"array":typeof value,"runtime",reqStr(o,"changed_by",64),t)); s.push(write(db,"INSERT INTO audit_runtime_config_history(config_key,old_value_json,new_value_json,changed_by,source_ip,changed_at) VALUES(?,?,?,?,?,?)",key,old?.value_json??null,v,reqStr(o,"changed_by",64),str(o.source_ip,"source_ip",64)??"",t)) } await db.batch(s); return { updated:entries.length } }
    case "runtime_config_history": { const x=page(o); return paged(db,"SELECT id,config_key,old_value_json,new_value_json,changed_by,source_ip,changed_at FROM audit_runtime_config_history ORDER BY changed_at DESC,id DESC","SELECT COUNT(*) AS total FROM audit_runtime_config_history",[],x.offset,x.size) }
    case "recent_events": return all(db,"SELECT id,event_time,node_id,event_hash,user_email,src,dest_host,dest_port,protocol,status,detour,reason,is_domain FROM audit_access_events WHERE event_time>=? ORDER BY event_time DESC,id DESC LIMIT ?",ago(num(o.seconds,"seconds",1,86400),"seconds"),limit(o.limit,200))
    case "user_visits": case "user_visits_paged": { const r=range(o), x=page(o), args=[reqStr(o,"email",191),r.from,r.to]; const q="SELECT event_time,user_email,src,dest_host,dest_port,protocol,status,detour,reason,is_domain,node_id,event_hash FROM audit_access_events WHERE user_email=? AND event_time>=? AND event_time<=? ORDER BY event_time DESC,id DESC"; return name === "user_visits" ? all(db,`${q} LIMIT ?`,...args,limit(o.limit,500)) : paged(db,q,"SELECT COUNT(*) AS total FROM audit_access_events WHERE user_email=? AND event_time>=? AND event_time<=?",args,x.offset,x.size) }
    case "query_events": { const r=range(o),x=page(o), f=["event_time>=?","event_time<=?"]; const args:unknown[]=[r.from,r.to]; if(o.email){f.push("user_email=?");args.push(o.email)} if(o.dest_host){f.push("dest_host LIKE ?");args.push(`%${o.dest_host}%`)} if(o.status){f.push("status=?");args.push(o.status)} if(o.detour){f.push("detour LIKE ?");args.push(`%${o.detour}%`)} if(typeof o.is_domain === "boolean"){f.push("is_domain=?");args.push(o.is_domain?1:0)} const where=f.join(" AND "); return paged(db,"SELECT id,event_time,node_id,event_hash,user_email,src,dest_host,dest_port,protocol,status,detour,reason,is_domain FROM audit_access_events WHERE "+where+" ORDER BY event_time DESC,id DESC","SELECT COUNT(*) AS total FROM audit_access_events WHERE "+where,args,x.offset,x.size) }
    case "list_users": { const r=range(o),x=page(o), args=[r.from,r.to]; return paged(db,"SELECT user_email,COUNT(*) AS count,MAX(event_time) AS last_seen,COUNT(DISTINCT NULLIF(dest_host,'')) AS unique_dest_host_count FROM audit_access_events WHERE event_time>=? AND event_time<=? AND user_email NOT IN ('','unknown') GROUP BY user_email ORDER BY last_seen DESC","SELECT COUNT(*) AS total FROM (SELECT user_email FROM audit_access_events WHERE event_time>=? AND event_time<=? AND user_email NOT IN ('','unknown') GROUP BY user_email)",args,x.offset,x.size) }
    case "summary_stats": { const s=num(o.window_seconds,"window_seconds",1,31536000), row=await first(db,"SELECT COUNT(*) AS total_events,COUNT(DISTINCT CASE WHEN user_email NOT IN ('','unknown') THEN user_email END) AS unique_users,COUNT(DISTINCT CASE WHEN is_domain=1 THEN NULLIF(dest_host,'') END) AS unique_domains FROM audit_access_events WHERE event_time>=?",ago(s,"seconds")); const total=Number(row?.total_events??0); return {total_events:total,unique_users:Number(row?.unique_users??0),unique_domains:Number(row?.unique_domains??0),qpm:Number((total/(s/60)).toFixed(2))} }
    case "job_state_get": return first(db,"SELECT value_text FROM audit_job_state WHERE state_key=?",reqStr(o,"key",128))
    case "job_state_set": return db.prepare("INSERT INTO audit_job_state(state_key,value_text,updated_at) VALUES(?,?,?) ON CONFLICT(state_key) DO UPDATE SET value_text=excluded.value_text,updated_at=excluded.updated_at").bind(reqStr(o,"key",128),reqStr(o,"value",100000),now()).run()
    case "geo_cache_get": { if(!Array.isArray(o.ips)||o.ips.length>99)throw new Bad("INVALID_INPUT","ips must contain at most 99 items");if(!o.ips.length)return {};const ttl=num(o.ttl_hours,"ttl_hours",1,8760), rows=await all(db,"SELECT ip,country,region,city,isp,addr,status,source,updated_at FROM audit_ip_geo_cache WHERE updated_at>=? AND ip IN ("+o.ips.map(()=>"?").join(",")+")",ago(ttl,"hours"),...o.ips); return Object.fromEntries(rows.map(x=>[x.ip,x])) }
    case "geo_cache_upsert": { if(!Array.isArray(o.rows)||o.rows.length>MAX.batch)throw new Bad("INVALID_INPUT","rows must contain at most 100 items");if(!o.rows.length)return {updated:0}; await db.batch((o.rows as Input[]).map(x=>write(db,"INSERT INTO audit_ip_geo_cache(ip,country,region,city,isp,addr,status,source,raw_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ip) DO UPDATE SET country=excluded.country,region=excluded.region,city=excluded.city,isp=excluded.isp,addr=excluded.addr,status=excluded.status,source=excluded.source,raw_json=excluded.raw_json,updated_at=excluded.updated_at",reqStr(x,"ip",45),str(x.country,"country",64)??"",str(x.region,"region",128)??"",str(x.city,"city",128)??"",str(x.isp,"isp",128)??"",str(x.addr,"addr",255)??"",str(x.status,"status",16)??"ok",str(x.source,"source",32)??"pconline",json(x.raw,"raw"),now()))); return {updated:(o.rows as unknown[]).length} }
    case "top_domains": return all(db,"SELECT dest_host AS domain,COUNT(*) AS hits FROM audit_access_events WHERE event_time>=? AND dest_host<>'' AND is_domain=1 GROUP BY dest_host ORDER BY hits DESC LIMIT ?",ago(num(o.seconds,"seconds",1,31536000),"seconds"),limit(o.limit,20))
    case "active_users": return all(db,"SELECT user_email,MAX(event_time) AS last_seen FROM audit_access_events INDEXED BY idx_access_time WHERE user_email NOT IN ('','unknown') AND event_time>=? GROUP BY user_email ORDER BY last_seen DESC LIMIT ?",ago(num(o.seconds,"seconds",1,31536000),"seconds"),limit(o.limit,200))
    case "migration_import": {
      const schemas: Record<string, { pk: string, columns: string[] }> = {
        audit_access_events: {pk:"id",columns:["id","event_time","user_email","src","dest_host","dest_port","protocol","status","detour","reason","is_domain","node_id","event_hash"]},
        audit_auth_events: {pk:"id",columns:["id","event_type","username","source_ip","user_agent","event_time"]},
        audit_admin_users: {pk:"id",columns:["id","username","password_hash","token_version","is_enabled","must_change_password","last_login_at","created_at","updated_at"]},
        audit_runtime_config: {pk:"config_key",columns:["config_key","value_json","value_type","scope","updated_by","updated_at"]},
        audit_runtime_config_history: {pk:"id",columns:["id","config_key","old_value_json","new_value_json","changed_by","source_ip","changed_at"]},
        audit_job_state: {pk:"state_key",columns:["state_key","value_text","updated_at"]}, collector_state: {pk:"id",columns:["id","file_path","inode","last_offset","updated_at"]},
        audit_ip_geo_cache: {pk:"ip",columns:["ip","country","region","city","isp","addr","status","source","raw_json","updated_at"]}
      }
      const table = reqStr(o, "table", 64), schema = schemas[table], rows = o.rows
      if (!schema || !Array.isArray(rows) || rows.length > MAX.ingestBatch) throw new Bad("INVALID_INPUT", "table is not importable or rows exceed 50")
      const statements = (rows as Input[]).map(row => {
        const present = schema.columns.filter(c => Object.prototype.hasOwnProperty.call(row, c)); if (!present.includes(schema.pk)) throw new Bad("INVALID_INPUT", `each imported row must contain ${schema.pk}`)
        const updates = present.filter(c => c !== schema.pk).map(c => `${c}=excluded.${c}`).join(",")
        return write(db, `INSERT INTO ${table}(${present.join(",")}) VALUES(${present.map(() => "?").join(",")}) ON CONFLICT(${schema.pk}) DO UPDATE SET ${updates}`, ...present.map(c => row[c] === undefined ? null : typeof row[c] === "object" ? json(row[c], c) : row[c]))
      })
      for (let i = 0; i < statements.length; i += 100) await db.batch(statements.slice(i, i + 100)); return { imported: rows.length, table }
    }
    case "migration_stats": { const tables:Record<string,string>={audit_access_events:"id",audit_auth_events:"id",audit_admin_users:"id",audit_runtime_config:"config_key",audit_runtime_config_history:"id",audit_job_state:"state_key",collector_state:"id",audit_ip_geo_cache:"ip"};const starts=(o.start_pks&&typeof o.start_pks==="object"&&!Array.isArray(o.start_pks)?o.start_pks:{}) as Input,ends=(o.end_pks&&typeof o.end_pks==="object"&&!Array.isArray(o.end_pks)?o.end_pks:{}) as Input,out:Record<string,number>={};for(const [t,pk] of Object.entries(tables)){const filters:string[]=[],args:unknown[]=[];if(starts[t]!==undefined){filters.push(`${pk}>?`);args.push(starts[t])}if(ends[t]!==undefined){filters.push(`${pk}<=?`);args.push(ends[t])}out[t]=Number((await first(db,`SELECT COUNT(*) total FROM ${t}${filters.length?` WHERE ${filters.join(" AND ")}`:""}`,...args))?.total??0)}return out }
    default: throw new Bad("UNKNOWN_OPERATION", "unsupported storage operation")
  }
}

export default { async fetch(request: Request, env: Env): Promise<Response> {
  if (request.method === "GET" && new URL(request.url).pathname === "/health") return ok({ status: "ok", timestamp: now() })
  if (request.method !== "POST") return fail(new Bad("NOT_FOUND", "not found"))
  const match = new URL(request.url).pathname.match(/^\/v1\/storage\/([a-z0-9_]+)$/); if (!match) return fail(new Bad("NOT_FOUND", "not found"))
  if (typeof env.GATEWAY_TOKEN !== "string" || env.GATEWAY_TOKEN.length < 32) return fail(new Bad("CONFIGURATION_ERROR", "gateway secret is not configured"))
  const auth = request.headers.get("Authorization"); if (!auth || auth.length !== `Bearer ${env.GATEWAY_TOKEN}`.length || auth !== `Bearer ${env.GATEWAY_TOKEN}`) return fail(new Bad("UNAUTHORIZED", "unauthorized"))
  try { const body=await request.json() as Input; if(!body || typeof body!=="object" || Array.isArray(body))throw new Bad("INVALID_INPUT","JSON body must be an object"); return ok(await operation(env.DB,match[1],body)) } catch(e) { return fail(e) }
} }
