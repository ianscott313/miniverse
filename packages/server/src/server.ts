import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { WebSocketServer, WebSocket } from 'ws';
import { mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { AgentStore } from './store.js';
import { EventLog, type WorldEvent } from './events.js';
import { getFrontendHtml } from './frontend.js';

export interface MiniverseServerConfig {
  port?: number;
  offlineTimeout?: number;
  /** Directory for generated assets (e.g. './public') */
  publicDir?: string;
}

export class MiniverseServer {
  private store: AgentStore;
  private events: EventLog;
  private httpServer: ReturnType<typeof createServer>;
  private wss: WebSocketServer;
  private port: number;
  private clients: Set<WebSocket> = new Set();
  /** Agent ID → WebSocket (for direct messaging) */
  private agentSockets: Map<string, WebSocket> = new Map();
  /** Channel name → set of member agent IDs */
  private channels: Map<string, Set<string>> = new Map();
  /** Inbox: queued messages for agents without a WebSocket */
  private inbox: Map<string, { from: string; message: string; channel?: string; timestamp: number }[]> = new Map();
  /** Webhook callbacks: agent ID → callback URL */
  private webhooks: Map<string, string> = new Map();
  private publicDir: string | null;
  /** World ID → world.json data cache */
  private worldCache: Map<string, unknown> = new Map();

  constructor(config: MiniverseServerConfig = {}) {
    this.port = config.port ?? 4321;
    this.publicDir = config.publicDir ?? null;
    this.store = new AgentStore(config.offlineTimeout ?? 30000);
    this.events = new EventLog();

    this.httpServer = createServer((req, res) => this.handleHttp(req, res));
    this.wss = new WebSocketServer({ server: this.httpServer });

    this.wss.on('connection', (ws) => {
      this.clients.add(ws);
      // Send current state immediately
      ws.send(JSON.stringify({ type: 'agents', agents: this.store.getPublicList() }));
      // Handle incoming messages (interactive mode)
      ws.on('message', (raw) => this.handleWsMessage(ws, raw));
      ws.on('close', () => {
        this.clients.delete(ws);
        // Remove agent→socket binding and channel memberships
        for (const [id, sock] of this.agentSockets) {
          if (sock === ws) {
            this.agentSockets.delete(id);
            for (const members of this.channels.values()) {
              members.delete(id);
            }
          }
        }
      });
    });

    this.store.onUpdate(() => this.broadcast());

    // Broadcast events in real time
    this.events.onEvent((event) => {
      const msg = JSON.stringify({ type: 'event', event });
      for (const ws of this.clients) {
        if (ws.readyState === WebSocket.OPEN) ws.send(msg);
      }
    });
  }

  async start(): Promise<number> {
    this.store.start();

    return new Promise((resolve, reject) => {
      this.httpServer.on('error', (err: NodeJS.ErrnoException) => {
        if (err.code === 'EADDRINUSE') {
          // Try next port
          this.port++;
          this.httpServer.listen(this.port, () => resolve(this.port));
        } else {
          reject(err);
        }
      });
      this.httpServer.listen(this.port, () => resolve(this.port));
    });
  }

  stop() {
    this.store.stop();
    for (const ws of this.clients) ws.close();
    this.wss.close();
    this.httpServer.close();
  }

  getPort(): number {
    return this.port;
  }

  private broadcast() {
    const msg = JSON.stringify({ type: 'agents', agents: this.store.getPublicList() });
    for (const ws of this.clients) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(msg);
      }
    }
  }

  // --- Interactive protocol ---

  private handleWsMessage(ws: WebSocket, raw: unknown) {
    try {
      const msg = JSON.parse(String(raw));

      // Bind agent ID to this WebSocket on any identified message
      if (msg.agent) {
        this.agentSockets.set(msg.agent, ws);
      }

      if (msg.type === 'action' && msg.agent && msg.action) {
        this.handleAction(msg.agent, msg.action, ws);
      } else if (msg.type === 'observe' && msg.agent) {
        const snapshot = this.buildSnapshot(msg.since);
        ws.send(JSON.stringify({ type: 'world', snapshot }));
      }
    } catch {
      // Ignore malformed messages
    }
  }

  private handleAction(agentId: string, action: { type: string; [key: string]: unknown }, senderWs?: WebSocket) {
    const actionType = action.type;

    if (actionType === 'move' && typeof action.to === 'string') {
      this.store.heartbeat({ agent: agentId, metadata: { moveTo: action.to } });
      this.events.push(agentId, action);

    } else if (actionType === 'speak' && typeof action.message === 'string') {
      this.store.heartbeat({
        agent: agentId,
        state: 'speaking',
        task: action.message as string,
        metadata: { to: action.to ?? null },
      });
      this.events.push(agentId, action);

    } else if (actionType === 'emote' && typeof action.emote === 'string') {
      this.store.heartbeat({ agent: agentId, metadata: { emote: action.emote } });
      this.events.push(agentId, action);

    } else if (actionType === 'status') {
      this.store.heartbeat({
        agent: agentId,
        state: action.state as string | undefined,
        task: action.task as string | null | undefined,
        energy: action.energy as number | undefined,
      });
      this.events.push(agentId, action);

    } else if (actionType === 'message' && typeof action.message === 'string') {
      this.routeMessage(agentId, action);
      // Set sender to speaking state so they walk over and show speech bubble
      this.store.heartbeat({
        agent: agentId,
        state: 'speaking',
        task: truncate(action.message as string, 40),
      });

    } else if (actionType === 'join_channel' && typeof action.channel === 'string') {
      if (!this.channels.has(action.channel)) {
        this.channels.set(action.channel, new Set());
      }
      this.channels.get(action.channel)!.add(agentId);
      // Bind WS if provided via HTTP
      if (senderWs) this.agentSockets.set(agentId, senderWs);

    } else if (actionType === 'leave_channel' && typeof action.channel === 'string') {
      this.channels.get(action.channel)?.delete(agentId);

    } else if (['paint_tile', 'place_prop', 'remove_prop', 'save_world', 'query_world', 'generate_texture', 'generate_prop'].includes(actionType)) {
      // World-editing actions are handled async — result goes to agent's inbox
      this.handleWorldAction(agentId, action);
    }
    // Unknown action types are silently ignored — forward compatible
  }

  /** Queue a message in an agent's inbox (for HTTP-based agents) */
  private queueInbox(agentId: string, from: string, message: string, channel?: string) {
    if (!this.inbox.has(agentId)) this.inbox.set(agentId, []);
    const q = this.inbox.get(agentId)!;
    q.push({ from, message, channel, timestamp: Date.now() });
    // Cap at 100 messages
    if (q.length > 100) q.shift();
    // Fire webhook if registered
    this.fireWebhook(agentId, from, message, channel);
  }

  /** POST to a registered webhook callback for an agent */
  private fireWebhook(agentId: string, from: string, message: string, channel?: string) {
    const url = this.webhooks.get(agentId);
    if (!url) return;
    const body = JSON.stringify({ agent: agentId, from, message, channel, timestamp: Date.now() });
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    }).catch(() => { /* silent fail — don't break message flow */ });
  }

  /** Drain and return all pending inbox messages for an agent */
  private drainInbox(agentId: string): { from: string; message: string; channel?: string; timestamp: number }[] {
    const msgs = this.inbox.get(agentId) ?? [];
    this.inbox.delete(agentId);
    return msgs;
  }

  /** Route a direct or channel message to the right WebSocket(s), with inbox fallback */
  private routeMessage(fromId: string, action: { type: string; [key: string]: unknown }) {
    const msg = JSON.stringify({
      type: 'message',
      from: fromId,
      message: action.message,
      channel: action.channel ?? undefined,
    });

    if (typeof action.channel === 'string') {
      const members = this.channels.get(action.channel);
      if (!members) return;
      for (const memberId of members) {
        if (memberId === fromId) continue;
        const ws = this.agentSockets.get(memberId);
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(msg);
        } else {
          this.queueInbox(memberId, fromId, action.message as string, action.channel);
        }
      }
    } else if (action.to) {
      const targets = Array.isArray(action.to) ? action.to : [action.to];
      for (const targetId of targets) {
        const ws = this.agentSockets.get(targetId);
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(msg);
        } else {
          this.queueInbox(targetId, fromId, action.message as string);
        }
      }
    }

    // Log as event (but message content stays private — only type + from + to/channel)
    this.events.push(fromId, {
      type: 'message',
      to: action.to ?? undefined,
      channel: action.channel ?? undefined,
    });
  }

  // --- World editing ---

  private getWorldPath(worldId: string): string {
    const publicDir = this.publicDir ?? './public';
    return path.join(publicDir, 'worlds', worldId, 'world.json');
  }

  private readWorld(worldId: string): Record<string, any> | null {
    const worldPath = this.getWorldPath(worldId);
    if (!existsSync(worldPath)) return null;
    try { return JSON.parse(readFileSync(worldPath, 'utf-8')); } catch { return null; }
  }

  private writeWorld(worldId: string, data: Record<string, any>) {
    const worldPath = this.getWorldPath(worldId);
    mkdirSync(path.dirname(worldPath), { recursive: true });
    writeFileSync(worldPath, JSON.stringify(data, null, 2) + '\n');
    this.worldCache.delete(worldId); // invalidate cache
  }

  private async handleWorldAction(agentId: string, action: { type: string; [key: string]: unknown }) {
    const worldId = (action.world as string) ?? 'cozy-startup';
    const actionType = action.type;

    try {
      if (actionType === 'query_world') {
        const world = this.readWorld(worldId);
        if (!world) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'World not found', world: worldId })); return; }
        // Return a summary, not the full floor grid
        const summary = {
          type: 'world_state',
          world: worldId,
          gridCols: world.gridCols,
          gridRows: world.gridRows,
          tiles: world.tiles ? Object.keys(world.tiles) : [],
          props: (world.props ?? []).map((p: any) => ({ id: p.id, x: p.x, y: p.y, w: p.w, h: p.h })),
          wanderPoints: world.wanderPoints ?? [],
        };
        this.queueInbox(agentId, 'system', JSON.stringify(summary));
        return;
      }

      if (actionType === 'paint_tile') {
        const { x, y, tile } = action as unknown as { x: number; y: number; tile: string };
        if (typeof x !== 'number' || typeof y !== 'number' || typeof tile !== 'string') {
          this.queueInbox(agentId, 'system', JSON.stringify({ error: 'paint_tile requires x, y, tile' }));
          return;
        }
        const world = this.readWorld(worldId);
        if (!world?.floor) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'World not found' })); return; }
        if (y < 0 || y >= world.floor.length || x < 0 || x >= (world.floor[0]?.length ?? 0)) {
          this.queueInbox(agentId, 'system', JSON.stringify({ error: 'Coordinates out of bounds' }));
          return;
        }
        world.floor[y][x] = tile;
        this.writeWorld(worldId, world);
        this.events.push(agentId, { type: 'paint_tile', x, y, tile, world: worldId });
        this.queueInbox(agentId, 'system', JSON.stringify({ ok: true, action: 'paint_tile', x, y, tile }));
        return;
      }

      if (actionType === 'place_prop') {
        const { id, x, y, w, h, layer } = action as any;
        if (!id || typeof x !== 'number' || typeof y !== 'number') {
          this.queueInbox(agentId, 'system', JSON.stringify({ error: 'place_prop requires id, x, y' }));
          return;
        }
        const world = this.readWorld(worldId);
        if (!world) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'World not found' })); return; }
        if (!world.props) world.props = [];
        // Remove existing prop with same id if present
        world.props = world.props.filter((p: any) => p.id !== id);
        world.props.push({ id, x, y, w: w ?? 1, h: h ?? 1, layer: layer ?? 'below' });
        this.writeWorld(worldId, world);
        this.events.push(agentId, { type: 'place_prop', id, x, y, world: worldId });
        this.queueInbox(agentId, 'system', JSON.stringify({ ok: true, action: 'place_prop', id, x, y }));
        return;
      }

      if (actionType === 'remove_prop') {
        const propId = action.id as string;
        if (!propId) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'remove_prop requires id' })); return; }
        const world = this.readWorld(worldId);
        if (!world) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'World not found' })); return; }
        const before = (world.props ?? []).length;
        world.props = (world.props ?? []).filter((p: any) => p.id !== propId);
        this.writeWorld(worldId, world);
        this.events.push(agentId, { type: 'remove_prop', id: propId, world: worldId });
        this.queueInbox(agentId, 'system', JSON.stringify({ ok: true, action: 'remove_prop', id: propId, removed: before !== world.props.length }));
        return;
      }

      if (actionType === 'generate_texture') {
        const { prompt, id } = action as unknown as { prompt: string; id: string };
        if (!prompt || !id) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'generate_texture requires prompt, id' })); return; }
        this.queueInbox(agentId, 'system', JSON.stringify({ status: 'generating', action: 'generate_texture', id }));

        let gen: any;
        try { gen = await import('@miniverse/generate'); } catch {
          this.queueInbox(agentId, 'system', JSON.stringify({ error: '@miniverse/generate not installed' }));
          return;
        }

        const publicDir = this.publicDir ?? './public';
        const tilesDir = path.join(publicDir, 'worlds', worldId, 'world_assets', 'tiles');
        mkdirSync(tilesDir, { recursive: true });
        const outPath = path.join(tilesDir, `${id}.png`);
        await gen.generateTexture({ prompt, output: outPath, size: 32 });

        // Add to world.json tiles map
        const world = this.readWorld(worldId);
        if (world) {
          if (!world.tiles) world.tiles = {};
          world.tiles[id] = `/world_assets/tiles/${id}.png`;
          this.writeWorld(worldId, world);
        }

        this.events.push(agentId, { type: 'generate_texture', id, world: worldId });
        this.queueInbox(agentId, 'system', JSON.stringify({ ok: true, action: 'generate_texture', id, path: `/world_assets/tiles/${id}.png` }));
        return;
      }

      if (actionType === 'generate_prop') {
        const { prompt, id, w, h } = action as unknown as { prompt: string; id: string; w?: number; h?: number };
        if (!prompt || !id) { this.queueInbox(agentId, 'system', JSON.stringify({ error: 'generate_prop requires prompt, id' })); return; }
        this.queueInbox(agentId, 'system', JSON.stringify({ status: 'generating', action: 'generate_prop', id }));

        let gen: any;
        try { gen = await import('@miniverse/generate'); } catch {
          this.queueInbox(agentId, 'system', JSON.stringify({ error: '@miniverse/generate not installed' }));
          return;
        }

        const publicDir = this.publicDir ?? './public';
        const propsDir = path.join(publicDir, 'worlds', worldId, 'world_assets', 'props');
        mkdirSync(propsDir, { recursive: true });
        const existing = existsSync(propsDir) ? readdirSync(propsDir).filter((f: string) => f.startsWith('prop_')).length : 0;
        const filename = `prop_${existing}_${id}.png`;
        const outPath = path.join(propsDir, filename);
        await gen.generateObject({ prompt, output: outPath });

        // Add to world.json propImages
        const world = this.readWorld(worldId);
        if (world) {
          if (!world.propImages) world.propImages = {};
          world.propImages[id] = `/world_assets/props/${filename}`;
          this.writeWorld(worldId, world);
        }

        this.events.push(agentId, { type: 'generate_prop', id, world: worldId });
        this.queueInbox(agentId, 'system', JSON.stringify({ ok: true, action: 'generate_prop', id, path: `/world_assets/props/${filename}`, w: w ?? 1, h: h ?? 1 }));
        return;
      }

      if (actionType === 'save_world') {
        // Explicit save — currently all edits auto-save, so this is a no-op confirmation
        this.queueInbox(agentId, 'system', JSON.stringify({ ok: true, action: 'save_world', note: 'All edits auto-save to world.json' }));
        return;
      }

    } catch (err: any) {
      this.queueInbox(agentId, 'system', JSON.stringify({ error: err.message ?? String(err) }));
    }
  }

  private buildSnapshot(sinceEventId?: number) {
    return {
      agents: this.store.getPublicList(),
      events: sinceEventId ? this.events.since(sinceEventId) : this.events.recent(50),
      lastEventId: this.events.lastId(),
    };
  }

  // --- Claude Code hook translation ---

  /** Keepalive intervals for hook-based agents so they don't time out between interactions */
  private keepalives: Map<string, ReturnType<typeof setInterval>> = new Map();

  private startKeepalive(agentId: string, agentName: string) {
    this.stopKeepalive(agentId);
    const interval = setInterval(() => {
      this.store.heartbeat({ agent: agentId, name: agentName });
    }, 15000);
    this.keepalives.set(agentId, interval);
  }

  private stopKeepalive(agentId: string) {
    const existing = this.keepalives.get(agentId);
    if (existing) {
      clearInterval(existing);
      this.keepalives.delete(agentId);
    }
  }

  /** Track sub-agent keepalives so we can clean them up with the parent */
  private subagentKeepAlives: Map<string, Set<string>> = new Map();

  private handleClaudeCodeHook(data: Record<string, unknown>) {
    const event = data.hook_event_name as string | undefined;
    if (!event) return;

    // Derive agent ID from session_id (unique per instance) + cwd (human-readable)
    const sessionId = data.session_id as string | undefined;
    const cwd = data.cwd as string | undefined;
    const folder = (cwd ?? '').split('/').pop() || 'code';
    const shortSession = sessionId ? sessionId.slice(0, 6) : '';

    const agentId = (data as any).agent
      ?? (shortSession ? `claude-${folder}-${shortSession}` : `claude-${folder}`);
    const agentName = (data as any).name
      ?? (shortSession ? `Claude (${folder} #${shortSession})` : `Claude (${folder})`);

    const toolName = data.tool_name as string | undefined;
    const prompt = data.prompt as string | undefined;

    // Sub-agent fields
    const subagentId = data.subagent_id as string | undefined;
    const subagentTask = data.subagent_task as string | undefined;

    switch (event) {
      case 'SessionStart':
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'idle' });
        this.events.push(agentId, { type: 'status', state: 'idle' });
        this.startKeepalive(agentId, agentName);
        break;

      case 'UserPromptSubmit':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'thinking',
          task: prompt ? truncate(prompt, 60) : 'Processing request',
        });
        this.events.push(agentId, { type: 'status', state: 'thinking' });
        this.startKeepalive(agentId, agentName);
        break;

      case 'PreToolUse':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'working',
          task: toolName ?? 'Using tool',
        });
        break;

      case 'PostToolUse':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'working',
          task: toolName ? `Done: ${toolName}` : 'Tool complete',
        });
        break;

      case 'PostToolUseFailure':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'error',
          task: toolName ? `Failed: ${toolName}` : 'Tool failed',
        });
        this.events.push(agentId, { type: 'status', state: 'error' });
        break;

      case 'Stop':
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'idle', task: null });
        this.events.push(agentId, { type: 'status', state: 'idle' });
        break;

      case 'SubagentStart': {
        // Register sub-agent as its own citizen
        const subId = subagentId
          ? `${agentId}-sub-${subagentId.slice(0, 6)}`
          : `${agentId}-sub-${Math.random().toString(36).slice(2, 8)}`;
        const subName = subagentTask
          ? `Claude (${truncate(subagentTask, 20)})`
          : `Claude (sub of ${folder})`;
        this.store.heartbeat({ agent: subId, name: subName, state: 'working', task: subagentTask ?? 'Running' });
        this.startKeepalive(subId, subName);
        // Track sub-agent under parent so we can clean up on SessionEnd
        if (!this.subagentKeepAlives.has(agentId)) this.subagentKeepAlives.set(agentId, new Set());
        this.subagentKeepAlives.get(agentId)!.add(subId);
        // Also update parent
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'working', task: 'Running subagent' });
        break;
      }

      case 'SubagentStop': {
        // Find and offline the sub-agent
        const subs = this.subagentKeepAlives.get(agentId);
        if (subs) {
          // If we have a subagentId, match it; otherwise pop the most recent
          let matchedSubId: string | undefined;
          if (subagentId) {
            const prefix = `${agentId}-sub-${subagentId.slice(0, 6)}`;
            for (const id of subs) {
              if (id === prefix) { matchedSubId = id; break; }
            }
          }
          if (!matchedSubId) matchedSubId = [...subs].pop();
          if (matchedSubId) {
            this.stopKeepalive(matchedSubId);
            this.store.heartbeat({ agent: matchedSubId, name: matchedSubId, state: 'offline', task: null });
            subs.delete(matchedSubId);
          }
        }
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'working', task: 'Subagent complete' });
        break;
      }

      case 'SessionEnd': {
        this.stopKeepalive(agentId);
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'offline', task: null });
        this.events.push(agentId, { type: 'status', state: 'offline' });
        // Clean up any sub-agents
        const subs = this.subagentKeepAlives.get(agentId);
        if (subs) {
          for (const subId of subs) {
            this.stopKeepalive(subId);
            this.store.heartbeat({ agent: subId, name: subId, state: 'offline', task: null });
          }
          this.subagentKeepAlives.delete(agentId);
        }
        break;
      }
    }
  }

  private handleCopilotCliHook(data: Record<string, unknown>) {
    const event = data.hook_event_name as string | undefined;
    if (!event) return;

    // Derive agent ID from session_id (unique per instance) + cwd (human-readable)
    const sessionId = data.session_id as string | undefined;
    const cwd = data.cwd as string | undefined;
    const folder = (cwd ?? '').split(/[\\/]/).filter(Boolean).pop() || 'code';
    const shortSession = sessionId ? sessionId.slice(0, 6) : '';

    const agentId = (data as any).agent
      ?? (shortSession ? `copilot-${folder}-${shortSession}` : `copilot-${folder}`);
    const agentName = (data as any).name
      ?? (shortSession ? `Copilot (${folder} #${shortSession})` : `Copilot (${folder})`);

    const toolName = data.tool_name as string | undefined;
    const prompt = data.prompt as string | undefined;
    const model = data.model as string | undefined;
    const metadata = model ? { model } : undefined;

    // Sub-agent fields
    const subagentId = data.subagent_id as string | undefined;
    const subagentTask = data.subagent_task as string | undefined;

    switch (event) {
      case 'SessionStart':
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'idle', metadata });
        this.events.push(agentId, { type: 'status', state: 'idle' });
        this.startKeepalive(agentId, agentName);
        break;

      case 'UserPromptSubmit':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'thinking',
          task: prompt ? truncate(prompt, 60) : 'Processing request',
          metadata,
        });
        this.events.push(agentId, { type: 'status', state: 'thinking' });
        this.startKeepalive(agentId, agentName);
        break;

      case 'PreToolUse':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'working',
          task: toolName ?? 'Using tool',
          metadata,
        });
        break;

      case 'PostToolUse':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'working',
          task: toolName ? `Done: ${toolName}` : 'Tool complete',
          metadata,
        });
        break;

      case 'PostToolUseFailure':
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'error',
          task: toolName ? `Failed: ${toolName}` : 'Tool failed',
          metadata,
        });
        this.events.push(agentId, { type: 'status', state: 'error' });
        break;

      case 'Stop':
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'idle', task: null, metadata });
        this.events.push(agentId, { type: 'status', state: 'idle' });
        break;

      case 'SubagentStart': {
        // Register sub-agent as its own citizen
        const subId = subagentId
          ? `${agentId}-sub-${subagentId.slice(0, 6)}`
          : `${agentId}-sub-${Math.random().toString(36).slice(2, 8)}`;
        const subName = subagentTask
          ? `Copilot (${truncate(subagentTask, 20)})`
          : `Copilot (sub of ${folder})`;
        this.store.heartbeat({
          agent: subId, name: subName, state: 'working', task: subagentTask ?? 'Running', metadata,
        });
        this.startKeepalive(subId, subName);
        // Track sub-agent under parent so we can clean up on SessionEnd
        if (!this.subagentKeepAlives.has(agentId)) this.subagentKeepAlives.set(agentId, new Set());
        this.subagentKeepAlives.get(agentId)!.add(subId);
        // Also update parent
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'working', task: 'Running subagent', metadata,
        });
        break;
      }

      case 'SubagentStop': {
        // Find and offline the sub-agent
        const subs = this.subagentKeepAlives.get(agentId);
        if (subs) {
          // If we have a subagentId, match it; otherwise pop the most recent
          let matchedSubId: string | undefined;
          if (subagentId) {
            const prefix = `${agentId}-sub-${subagentId.slice(0, 6)}`;
            for (const id of subs) {
              if (id === prefix) { matchedSubId = id; break; }
            }
          }
          if (!matchedSubId) matchedSubId = [...subs].pop();
          if (matchedSubId) {
            this.stopKeepalive(matchedSubId);
            this.store.heartbeat({ agent: matchedSubId, name: matchedSubId, state: 'offline', task: null, metadata });
            subs.delete(matchedSubId);
          }
        }
        this.store.heartbeat({
          agent: agentId, name: agentName, state: 'working', task: 'Subagent complete', metadata,
        });
        break;
      }

      case 'SessionEnd': {
        this.stopKeepalive(agentId);
        this.store.heartbeat({ agent: agentId, name: agentName, state: 'offline', task: null, metadata });
        this.events.push(agentId, { type: 'status', state: 'offline' });
        // Clean up any sub-agents
        const subs = this.subagentKeepAlives.get(agentId);
        if (subs) {
          for (const subId of subs) {
            this.stopKeepalive(subId);
            this.store.heartbeat({ agent: subId, name: subId, state: 'offline', task: null, metadata });
          }
          this.subagentKeepAlives.delete(agentId);
        }
        break;
      }
    }
  }

  private getDefaultWorldId(): string | null {
    const publicDir = this.publicDir ?? './public';
    const worldsDir = path.join(publicDir, 'worlds');
    if (!existsSync(worldsDir)) return null;
    try {
      const dirs = readdirSync(worldsDir).filter(d => {
        return existsSync(path.join(worldsDir, d, 'world.json'));
      });
      return dirs[0] ?? null;
    } catch { return null; }
  }

  private loadWorldData(worldId: string): unknown | null {
    if (this.worldCache.has(worldId)) return this.worldCache.get(worldId);
    const publicDir = this.publicDir ?? './public';
    const worldPath = path.join(publicDir, 'worlds', worldId, 'world.json');
    if (!existsSync(worldPath)) return null;
    try {
      const data = JSON.parse(readFileSync(worldPath, 'utf-8'));
      this.worldCache.set(worldId, data);
      return data;
    } catch {
      return null;
    }
  }

  private async handleHttp(req: IncomingMessage, res: ServerResponse) {
    const url = new URL(req.url ?? '/', `http://localhost:${this.port}`);

    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    // Routes
    if (req.method === 'GET' && url.pathname === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(getFrontendHtml(this.port));
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/info') {
      const agents = this.store.getPublicList();
      const online = agents.filter((a: any) => a.state !== 'offline').length;
      const worldId = this.getDefaultWorldId();
      const world = worldId ? this.readWorld(worldId) : null;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        miniverse: true,
        version: '0.2.8',
        agents: { online, total: agents.length },
        world: worldId ?? null,
        grid: world ? { cols: world.gridCols ?? 16, rows: world.gridRows ?? 12 } : null,
      }));
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/agents') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ agents: this.store.getPublicList() }));
      return;
    }

    if (req.method === 'POST' && url.pathname === '/api/heartbeat') {
      try {
        const body = await readBody(req);
        const data = JSON.parse(body);

        if (!data.agent) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing required field: agent' }));
          return;
        }

        const agent = this.store.heartbeat(data);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, agent: { ...agent, lastSeen: undefined } }));
      } catch (err) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid JSON body' }));
      }
      return;
    }

    if (req.method === 'POST' && url.pathname === '/api/agents/remove') {
      try {
        const body = await readBody(req);
        const data = JSON.parse(body);
        if (data.agent) this.store.remove(data.agent);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
      } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid JSON body' }));
      }
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/inbox') {
      const agent = url.searchParams.get('agent');
      if (!agent) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Missing ?agent= param' }));
        return;
      }
      const peek = url.searchParams.get('peek') === 'true';
      const messages = peek
        ? (this.inbox.get(agent) ?? [])
        : this.drainInbox(agent);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ messages }));
      return;
    }

    if (req.method === 'POST' && url.pathname === '/api/generate') {
      await this.handleGenerate(req, res);
      return;
    }

    // --- Webhook registration ---
    if (req.method === 'POST' && url.pathname === '/api/webhook') {
      const body = await readBody(req);
      const { agent, url: callbackUrl } = JSON.parse(body);
      if (!agent || !callbackUrl) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Missing agent or url' }));
        return;
      }
      this.webhooks.set(agent, callbackUrl);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, agent, url: callbackUrl }));
      return;
    }

    if (req.method === 'DELETE' && url.pathname === '/api/webhook') {
      const agent = url.searchParams.get('agent');
      if (agent) this.webhooks.delete(agent);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
      return;
    }

    // --- Claude Code hooks endpoint ---

    if (req.method === 'POST' && url.pathname.startsWith('/api/hooks/claude-code')) {
      try {
        const body = await readBody(req);
        const data = JSON.parse(body);
        // Allow overriding agent/name via query params
        const qAgent = url.searchParams.get('agent');
        const qName = url.searchParams.get('name');
        if (qAgent) data.agent = qAgent;
        if (qName) data.name = qName;
        this.handleClaudeCodeHook(data);
        res.writeHead(200);
        res.end();
      } catch {
        res.writeHead(200);
        res.end();
      }
      return;
    }

    if (req.method === 'POST' && url.pathname.startsWith('/api/hooks/copilot-cli')) {
      try {
        const body = await readBody(req);
        const data = JSON.parse(body);
        // Allow overriding agent/name via query params
        const qAgent = url.searchParams.get('agent');
        const qName = url.searchParams.get('name');
        if (qAgent) data.agent = qAgent;
        if (qName) data.name = qName;
        this.handleCopilotCliHook(data);
        res.writeHead(200);
        res.end();
      } catch {
        res.writeHead(200);
        res.end();
      }
      return;
    }

    // --- Interactive protocol endpoints ---

    if (req.method === 'GET' && url.pathname === '/api/observe') {
      const since = url.searchParams.get('since');
      const worldId = url.searchParams.get('world');
      const snapshot = this.buildSnapshot(since ? parseInt(since, 10) : undefined);
      const world = worldId ? this.loadWorldData(worldId) : null;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ...snapshot, world }));
      return;
    }

    if (req.method === 'POST' && url.pathname === '/api/act') {
      try {
        const body = await readBody(req);
        const data = JSON.parse(body);
        if (!data.agent || !data.action?.type) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing agent or action.type' }));
          return;
        }
        this.handleAction(data.agent, data.action);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
      } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid JSON body' }));
      }
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/channels') {
      const channels: Record<string, string[]> = {};
      for (const [name, members] of this.channels) {
        channels[name] = [...members];
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ channels }));
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/events') {
      const since = url.searchParams.get('since');
      const events = since ? this.events.since(parseInt(since, 10)) : this.events.recent(50);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ events, lastEventId: this.events.lastId() }));
      return;
    }

    // 404
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  }

  private async handleGenerate(req: IncomingMessage, res: ServerResponse) {
    const { readdirSync } = await import('node:fs');

    try {
      const body = await readBody(req);
      const data = JSON.parse(body);

      if (!data.prompt || !data.type) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Missing prompt or type' }));
        return;
      }

      if (data.falKey) process.env.FAL_KEY = data.falKey;
      if (!process.env.FAL_KEY) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'No FAL_KEY. Set it in the Generate tab or as an environment variable.' }));
        return;
      }

      let gen: any;
      try {
        gen = await import('@miniverse/generate');
      } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Install @miniverse/generate: npm i @miniverse/generate' }));
        return;
      }

      const publicDir = this.publicDir ?? './public';
      const slug = data.prompt.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40);
      const worldId = (data.worldId || '').replace(/[^a-zA-Z0-9_-]/g, '');
      const worldDir = worldId ? path.join(publicDir, 'worlds', worldId) : publicDir;

      // Handle base64 reference image
      let refImage: string | undefined;
      if (data.image) {
        const tmpPath = path.join(tmpdir(), `miniverse_ref_${Date.now()}.png`);
        writeFileSync(tmpPath, Buffer.from(data.image, 'base64'));
        refImage = tmpPath;
      }

      let resultPath: string;
      let resultId: string;

      if (data.type === 'props') {
        const spritesDir = path.join(worldDir, 'sprites');
        mkdirSync(spritesDir, { recursive: true });
        const existing = readdirSync(spritesDir).filter((f: string) => f.startsWith('prop_'));
        const nextIdx = existing.length;
        resultId = slug || 'prop';
        const filename = `prop_${nextIdx}_${resultId}.png`;
        const outPath = path.join(spritesDir, filename);
        await gen.generateObject({ prompt: data.prompt, refImage, output: outPath });
        resultPath = worldId ? `/worlds/${worldId}/sprites/${filename}` : `/sprites/${filename}`;
      } else if (data.type === 'texture') {
        resultId = slug || 'texture';
        const filename = `${resultId}.png`;
        const tilesDir = path.join(worldDir, 'tiles');
        mkdirSync(tilesDir, { recursive: true });
        const outPath = path.join(tilesDir, filename);
        await gen.generateTexture({ prompt: data.prompt, refImage, output: outPath, size: 32 });
        resultPath = worldId ? `/worlds/${worldId}/tiles/${filename}` : `/tiles/${filename}`;
      } else if (data.type === 'character') {
        resultId = slug || 'character';
        const filename = `${resultId}_walk.png`;
        const spritesDir = path.join(publicDir, 'sprites');
        mkdirSync(spritesDir, { recursive: true });
        const outPath = path.join(spritesDir, filename);
        await gen.generateCharacter({ prompt: data.prompt, refImage, type: 'walk', output: outPath });
        resultPath = `/sprites/${filename}`;
      } else {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid type. Use: props, texture, character' }));
        return;
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, path: resultPath, id: resultId, type: data.type }));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: String(err) }));
    }
  }
}

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max - 1) + '\u2026';
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
    req.on('error', reject);
  });
}
