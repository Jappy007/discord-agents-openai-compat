/**
 * Mineflayer bridge for Discord Agents.
 *
 * One process, two interfaces:
 *   1. JSON lines over stdio  (chat events out, chat sends in)
 *   2. MCP HTTP server on localhost:3001 (action tools)
 *
 * Config is read from stdin as the first line of JSON, then the process emits
 * events and waits for commands. If no config arrives within 10s it falls back
 * to environment variables.
 */

const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals: { GoalNear, GoalFollow, GoalBlock } } = require('mineflayer-pathfinder');
const http = require('http');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const MCP_PORT = process.env.MC_MCP_PORT || 3001;
const AUTH_CACHE = path.join(__dirname, '.minecraft_session_cache.json');

let bot = null;
let config = null;
let reconnectTimer = null;
let mcpServer = null;
let connected = false;
let shuttingDown = false;

// Track players currently online, aggression state, and blocks placed by us.
const onlinePlayers = new Map(); // uuid -> {name, lastSeen}
const aggression = new Map();    // uuid -> {weaponHits, fistHits, lastSwing}
const ownPlaced = new Set();     // "x,y,z" keys

const NEVER_TOUCH_BLOCKS = new Set([
  'chest', 'trapped_chest', 'ender_chest', 'barrel',
  'crafting_table', 'furnace', 'blast_furnace', 'smoker',
  'bed', 'door', 'iron_door', 'spruce_door', 'birch_door', 'jungle_door',
  'acacia_door', 'dark_oak_door', 'mangrove_door', 'cherry_door', 'bamboo_door',
  'crimson_door', 'warped_door', 'oak_door', 'pale_oak_door',
  'trapdoor', 'iron_trapdoor', 'torch', 'soul_torch', 'redstone_torch',
  'lantern', 'soul_lantern', 'glowstone', 'sea_lantern', 'shroomlight',
  'froglight', 'end_rod', 'redstone_lamp', 'beacon', 'item_frame',
  'glow_item_frame', 'painting', 'sign', 'hanging_sign', 'lectern',
  'note_block', 'jukebox', 'dispenser', 'dropper', 'hopper', 'observer',
  'piston', 'sticky_piston', 'lever', 'button', 'pressure_plate',
  'respawn_anchor', 'lodestone', 'enchanting_table', 'anvil', 'chipped_anvil',
  'damaged_anvil', 'brewing_stand', 'cauldron', 'composter', 'loom',
  'smithing_table', 'grindstone', 'cartography_table', 'fletching_table',
  'stonecutter', 'skeleton_skull', 'wither_skeleton_skull', 'zombie_head',
  'creeper_head', 'dragon_head', 'player_head', 'skull',
]);

const NATURAL_BLOCKS = new Set([
  'stone', 'cobblestone', 'mossy_cobblestone', 'granite', 'diorite', 'andesite',
  'deepslate', 'cobbled_deepslate', 'tuff', 'calcite', 'dripstone_block',
  'dirt', 'coarse_dirt', 'podzol', 'mycelium', 'grass_block', 'mud',
  'sand', 'red_sand', 'gravel', 'clay', 'snow_block', 'snow', 'ice',
  'packed_ice', 'blue_ice', 'obsidian', 'netherrack', 'basalt',
  'smooth_basalt', 'blackstone', 'end_stone', 'coal_ore', 'iron_ore',
  'copper_ore', 'gold_ore', 'redstone_ore', 'lapis_ore', 'diamond_ore',
  'emerald_ore', 'nether_gold_ore', 'nether_quartz_ore', 'ancient_debris',
  'deepslate_coal_ore', 'deepslate_iron_ore', 'deepslate_copper_ore',
  'deepslate_gold_ore', 'deepslate_redstone_ore', 'deepslate_lapis_ore',
  'deepslate_diamond_ore', 'deepslate_emerald_ore', 'raw_iron_block',
  'raw_copper_block', 'raw_gold_block', 'oak_log', 'birch_log', 'spruce_log',
  'jungle_log', 'acacia_log', 'dark_oak_log', 'mangrove_log', 'cherry_log',
  'bamboo_block', 'crimson_stem', 'warped_stem', 'pale_oak_log',
  'oak_leaves', 'birch_leaves', 'spruce_leaves', 'jungle_leaves',
  'acacia_leaves', 'dark_oak_leaves', 'mangrove_leaves', 'cherry_leaves',
  'azalea_leaves', 'flowering_azalea_leaves', 'pale_oak_leaves',
  'grass', 'tall_grass', 'fern', 'large_fern', 'dead_bush',
  'dandelion', 'poppy', 'blue_orchid', 'allium', 'azure_bluet',
  'tulip', 'oxeye_daisy', 'cornflower', 'lily_of_the_valley',
  'wither_rose', 'sunflower', 'lilac', 'rose_bush', 'peony',
  'cactus', 'sugar_cane', 'vine', 'lily_pad', 'seagrass', 'kelp',
  'bamboo', 'wheat', 'carrots', 'potatoes', 'beetroots',
]);

function log(level, msg) {
  const line = JSON.stringify({ type: 'log', level, message: msg, ts: new Date().toISOString() });
  console.error(line); // logs on stderr so stdout stays pure JSON lines
}

function getTranslateKey(obj) {
  if (obj && obj.type === 'compound' && obj.value && obj.value.translate) {
    return obj.value.translate.value;
  }
  return null;
}

function emit(event) {
  console.log(JSON.stringify(event));
}

function loadAuthCache() {
  try {
    if (fs.existsSync(AUTH_CACHE)) {
      return JSON.parse(fs.readFileSync(AUTH_CACHE, 'utf8'));
    }
  } catch (e) {
    log('warn', 'failed to load auth cache: ' + e.message);
  }
  return null;
}

function saveAuthCache(data) {
  try {
    fs.writeFileSync(AUTH_CACHE, JSON.stringify(data, null, 2));
  } catch (e) {
    log('warn', 'failed to save auth cache: ' + e.message);
  }
}

function getConfig() {
  return {
    host: config.host || process.env.MC_HOST || 'localhost',
    port: parseInt(config.port || process.env.MC_PORT || 25565, 10),
    username: config.username || process.env.MC_USERNAME,
    password: config.password || process.env.MC_PASSWORD,
    auth: config.auth || process.env.MC_AUTH || 'microsoft',
    version: config.version || process.env.MC_VERSION || '1.26.2',
    botName: config.bot_name || process.env.MC_BOT_NAME || (config.username ? config.username.split('@')[0] : 'Bot'),
    spawn: config.spawn || null,
    spawnRadius: parseInt(config.spawn_radius || process.env.MC_SPAWN_RADIUS || 100, 10),
  };
}

function createBot() {
  const cfg = getConfig();
  const cache = loadAuthCache();
  const options = {
    host: cfg.host,
    port: cfg.port,
    username: cfg.username,
    auth: cfg.auth,
    version: cfg.version,
    profilesFolder: path.join(__dirname, '.minecraft'),
  };
  if (cache && cache.accessToken) {
    options.session = cache;
  }
  log('info', `connecting to ${cfg.host}:${cfg.port} as ${cfg.username} (version ${cfg.version})`);
  let b;
  try {
    b = mineflayer.createBot(options);
  } catch (e) {
    log('error', `Failed to create bot: ${e.message}\n${e.stack}`);
    throw e;
  }
  b.loadPlugin(pathfinder);
  log('info', 'bot created and plugins loaded');
  return b;
}

function posKey(p) {
  return `${Math.floor(p.x)},${Math.floor(p.y)},${Math.floor(p.z)}`;
}

function dist2d(a, b) {
  const dx = a.x - b.x;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dz * dz);
}

function isNearSpawn(pos) {
  const cfg = getConfig();
  if (!cfg.spawn) return false;
  const dx = pos.x - cfg.spawn.x;
  const dy = pos.y - cfg.spawn.y;
  const dz = pos.z - cfg.spawn.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz) <= cfg.spawnRadius;
}

function heldItemIsWeapon() {
  if (!bot || !bot.heldItem) return false;
  const name = bot.heldItem.name;
  return /sword|axe|trident|mace/.test(name);
}

function isPlayerBuildNearby(center) {
  if (!bot || !bot.findBlocks) return false;
  const buildMarkers = [];
  try {
    const blocks = bot.findBlocks({
      point: center,
      matching: (block) => {
        if (!block) return false;
        return NEVER_TOUCH_BLOCKS.has(block.name) ||
               /planks|slab|stair|brick|concrete|wool|terracotta|glass/.test(block.name);
      },
      maxDistance: 16,
      count: 32,
    });
    for (const p of blocks) {
      buildMarkers.push(posKey(p));
    }
  } catch (e) {
    log('warn', 'build scan error: ' + e.message);
  }
  return buildMarkers.length > 0;
}

function canBreakBlock(block) {
  if (!block) return { ok: false, reason: 'no block' };
  if (NEVER_TOUCH_BLOCKS.has(block.name)) {
    return { ok: false, reason: `refusing to break protected block: ${block.name}` };
  }
  if (ownPlaced.has(posKey(block.position))) {
    return { ok: true };
  }
  if (!NATURAL_BLOCKS.has(block.name)) {
    return { ok: false, reason: `not a natural block: ${block.name}` };
  }
  if (isNearSpawn(block.position)) {
    return { ok: false, reason: 'too close to spawn' };
  }
  if (isPlayerBuildNearby(block.position)) {
    return { ok: false, reason: 'player build nearby' };
  }
  return { ok: true };
}

function canPlaceBlock(pos) {
  if (isNearSpawn(pos)) {
    return { ok: false, reason: 'too close to spawn' };
  }
  if (isPlayerBuildNearby(pos)) {
    return { ok: false, reason: 'player build nearby' };
  }
  return { ok: true };
}

function chunkChat(text, maxLen = 256) {
  const out = [];
  while (text.length > maxLen) {
    let cut = text.lastIndexOf(' ', maxLen);
    if (cut < 0) cut = maxLen;
    out.push(text.slice(0, cut));
    text = text.slice(cut).trimStart();
  }
  if (text.length) out.push(text);
  return out;
}

async function sendChat(text) {
  if (!bot) return;
  const chunks = chunkChat(text);
  for (const chunk of chunks) {
    bot.chat(chunk);
    await new Promise(r => setTimeout(r, 600 + Math.random() * 400));
  }
}

function statusSnapshot() {
  if (!bot || !bot.entity) return null;
  const pos = bot.entity.position;
  const nearby = [];
  for (const [uuid, p] of onlinePlayers) {
    if (!p.position) continue;
    const d = dist2d(pos, p.position);
    if (d < 80) nearby.push({ name: p.name, distance: Math.round(d) });
  }
  nearby.sort((a, b) => a.distance - b.distance);
  return {
    position: { x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) },
    health: Math.round(bot.health * 10) / 10,
    food: bot.food,
    held: bot.heldItem ? bot.heldItem.name : 'empty',
    yaw: bot.entity.yaw,
    pitch: bot.entity.pitch,
    nearby: nearby.slice(0, 10),
    timeOfDay: bot.time.timeOfDay,
  };
}

function emitStatus() {
  const s = statusSnapshot();
  if (s) emit({ type: 'status', data: s });
}

async function handleChatCommand(cmd) {
  if (!bot) return;
  if (cmd.type === 'chat') {
    await sendChat(cmd.text);
  } else if (cmd.type === 'command') {
    bot.chat(cmd.text);
  } else if (cmd.type === 'whisper') {
    bot.whisper(cmd.player, cmd.text);
  }
}

// MCP tool handlers
const mcpTools = {
  mc_status: async () => statusSnapshot(),

  mc_goto: async (args) => {
    if (!bot) return { error: 'not connected' };
    const { x, y, z } = args;
    const goal = new GoalNear(parseFloat(x), parseFloat(y), parseFloat(z), 1);
    bot.pathfinder.setGoal(goal);
    return { status: 'moving', target: { x, y, z } };
  },

  mc_follow: async (args) => {
    if (!bot) return { error: 'not connected' };
    const target = bot.players[args.player];
    if (!target || !target.entity) return { error: `player ${args.player} not found` };
    const goal = new GoalFollow(target.entity, parseFloat(args.distance || 3));
    bot.pathfinder.setGoal(goal);
    return { status: 'following', player: args.player };
  },

  mc_look_at: async (args) => {
    if (!bot) return { error: 'not connected' };
    const target = bot.players[args.player];
    if (target && target.entity) {
      await bot.lookAt(target.entity.position.offset(0, target.entity.height, 0));
      return { status: 'looking_at_player', player: args.player };
    }
    await bot.lookAt(new Vec3(parseFloat(args.x), parseFloat(args.y), parseFloat(args.z)));
    return { status: 'looking_at', target: { x: args.x, y: args.y, z: args.z } };
  },

  mc_inventory: async () => {
    if (!bot) return { error: 'not connected' };
    const items = bot.inventory.items().map(i => ({ name: i.name, count: i.count }));
    return { items };
  },

  mc_equip: async (args) => {
    if (!bot) return { error: 'not connected' };
    const item = bot.inventory.items().find(i => i.name.includes(args.item));
    if (!item) return { error: `no item matching ${args.item}` };
    await bot.equip(item, 'hand');
    return { status: 'equipped', item: item.name };
  },

  mc_dig: async (args) => {
    if (!bot) return { error: 'not connected' };
    const target = bot.blockAt(new Vec3(parseFloat(args.x), parseFloat(args.y), parseFloat(args.z)));
    const check = canBreakBlock(target);
    if (!check.ok) return { error: check.reason };
    await bot.dig(target);
    return { status: 'dug', block: target.name, position: args };
  },

  mc_place: async (args) => {
    if (!bot) return { error: 'not connected' };
    const pos = new Vec3(parseFloat(args.x), parseFloat(args.y), parseFloat(args.z));
    const check = canPlaceBlock(pos);
    if (!check.ok) return { error: check.reason };
    const item = bot.inventory.items().find(i => i.name.includes(args.item || 'dirt'));
    if (!item) return { error: 'no suitable block in inventory' };
    const refBlock = bot.blockAt(pos.offset(0, -1, 0));
    await bot.equip(item, 'hand');
    await bot.placeBlock(refBlock, new Vec3(0, 1, 0));
    ownPlaced.add(posKey(pos));
    return { status: 'placed', item: item.name, position: args };
  },

  mc_attack: async (args) => {
    if (!bot) return { error: 'not connected' };
    const target = bot.players[args.target];
    if (target && target.entity) {
      const rec = aggression.get(target.uuid) || { weaponHits: 0, fistHits: 0 };
      if (rec.weaponHits === 0 && !args.force) {
        return { error: 'refusing to attack player: not provoked (use force only via explicit command)' };
      }
      bot.attack(target.entity);
      return { status: 'attacked', target: args.target };
    }
    const mob = Object.values(bot.entities).find(e => e.type !== 'player' && e.displayName === args.target);
    if (mob) {
      bot.attack(mob);
      return { status: 'attacked', target: args.target };
    }
    return { error: `target ${args.target} not found` };
  },

  mc_collect: async (args) => {
    if (!bot) return { error: 'not connected' };
    const itemEntity = bot.nearestEntity(e => e.name === 'item' && e.metadata && e.metadata[8] && e.metadata[8].itemId.includes(args.item));
    if (!itemEntity) return { error: `no nearby item matching ${args.item}` };
    bot.pathfinder.setGoal(new GoalNear(itemEntity.position.x, itemEntity.position.y, itemEntity.position.z, 1));
    return { status: 'collecting', item: args.item };
  },

  mc_craft: async (args) => {
    if (!bot) return { error: 'not connected' };
    const item = bot.registry.itemsByName[args.item];
    if (!item) return { error: `unknown item ${args.item}` };
    const recipe = bot.recipesFor(item.id, null, 1, null)[0];
    if (!recipe) return { error: `no recipe for ${args.item}` };
    await bot.craft(recipe, 1);
    return { status: 'crafted', item: args.item };
  },
};

function startMcpServer() {
  mcpServer = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.method !== 'POST' || req.url !== '/mcp/tool') {
      res.writeHead(404);
      res.end(JSON.stringify({ error: 'not found' }));
      return;
    }
    let body = '';
    req.on('data', c => body += c);
    req.on('end', async () => {
      try {
        const { tool, arguments: args } = JSON.parse(body);
        const handler = mcpTools[tool];
        if (!handler) {
          res.writeHead(400);
          res.end(JSON.stringify({ error: `unknown tool ${tool}` }));
          return;
        }
        const result = await handler(args || {});
        res.writeHead(200);
        res.end(JSON.stringify({ result }));
      } catch (e) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: e.message }));
      }
    });
  });
  mcpServer.listen(MCP_PORT, '127.0.0.1', () => {
    log('info', `MCP server listening on 127.0.0.1:${MCP_PORT}`);
  });
}

function setupBotEvents() {
  bot.on('login', () => {
    connected = true;
    log('info', `logged in as ${bot.username}`);
    const uuid = bot.player ? bot.player.uuid : "00000000-0000-0000-0000-000000000000";
    emit({ type: 'login', username: bot.username, uuid: uuid });
    if (bot._client.session) saveAuthCache(bot._client.session);
  });

  bot.on('spawn', () => {
    log('info', 'spawn event received');
    emit({ type: 'spawn', position: posKey(bot.entity.position) });
    emitStatus();
  });

  bot.on('error', (err) => {
    log('error', 'mineflayer error: ' + err.message + '\n' + (err.stack || ''));
  });

  bot.on('kicked', (reason) => {
    connected = false;
    log('error', 'kicked: ' + JSON.stringify(reason));
    emit({ type: 'kicked', reason });
  });

  bot.on('end', () => {
    connected = false;
    log('error', 'connection ended unexpectedly');
    emit({ type: 'end' });
    if (!shuttingDown) scheduleReconnect();
  });

  if (bot._client) {
    bot._client.on('error', (err) => {
      log('error', 'minecraft client socket error: ' + err.message + '\n' + (err.stack || ''));
    });

    bot._client.on('connect', () => {
      log('info', 'minecraft client connected to server socket');
    });

    // Log EVERY incoming packet by name so we can see what's actually arriving
    bot._client.on('packet', (data, packetMeta) => {
      // Ignore high-frequency noise packets (chunks, entity movement, time, light, registries)
      const name = packetMeta.name;
      if (
        name.includes('entity') ||
        name.includes('chunk') ||
        name.includes('light') ||
        name.includes('sound') ||
        name.includes('particle') ||
        name.includes('time') ||
        name.includes('block') ||
        name.includes('teleport') ||
        name.includes('head_rot') ||
        name.includes('look') ||
        name.includes('rel_move') ||
        name.includes('registry') ||
        name.includes('tags') ||
        name.includes('recipe')
      ) {
        return;
      }
      log('info', `[PKT: ${name}]: ${JSON.stringify(data)}`);
    });

    // Helper to recursively pull ONLY chat text out of prismarine NBT compound/list objects
    // Filters out color codes, hover events, click events, and other metadata
    function extractChatStrings(obj) {
      if (!obj) return [];
      if (typeof obj === 'string') {
        // Skip known color codes and metadata values
        if (/^(yellow|white|black|dark_blue|dark_green|dark_aqua|dark_red|dark_purple|gold|gray|dark_gray|blue|green|aqua|red|light_purple|show_entity|suggest_command|intArray|minecraft:player|QUOTABLE_PHRASE|SINGLE_WORD|GREEDY_PHRASE)$/.test(obj)) {
          return [];
        }
        return [obj];
      }
      if (Array.isArray(obj)) return obj.flatMap(extractChatStrings);
      if (obj.type === 'string' && typeof obj.value === 'string') {
        return extractChatStrings(obj.value);
      }
      if (obj.type === 'compound' && obj.value) return extractChatStrings(obj.value);
      if (obj.type === 'list' && obj.value) return extractChatStrings(obj.value);
      if (typeof obj === 'object') {
        let result = [];
        for (const k of Object.keys(obj)) {
          // Skip metadata fields that aren't actual chat text
          if (['color', 'hoverEvent', 'clickEvent', 'insertion', 'type', 'value', 'style'].includes(k)) continue;
          result = result.concat(extractChatStrings(obj[k]));
        }
        return result;
      }
      return [];
    }

    // 1. Handle disguised_chat (used by Folia/Paper and proxies when enforce-secure-profile is off/modified)
    bot._client.on('disguised_chat', (data) => {
      log('info', `[DISGUISED CHAT]: ${JSON.stringify(data)}`);
      try {
        const plainMsg = extractChatStrings(data.message).join(' ');
        const senderName = data.senderName || '';
        log('info', `[DISGUISED CHAT PARSED]: sender=${senderName} msg=${plainMsg}`);
        
        const match = plainMsg.match(/^[<\[]([a-zA-Z0-9_]{2,16})[>\]]\s+(.+)$/) ||
                      plainMsg.match(/^([a-zA-Z0-9_]{2,16}):\s+(.+)$/);
        
        const player = match ? match[1] : (senderName || 'player');
        const text = match ? match[2] : plainMsg;
        
        if (text && player !== bot.username) {
          emit({
            type: 'chat',
            player: player,
            uuid: data.sender || player,
            message: text,
            whisper: false,
          });
        }
      } catch (e) {
        log('error', `Error parsing disguised_chat: ${e.message}`);
      }
    });

    // 2. Handle player_chat (1.19+ signed chat packet)
    bot._client.on('player_chat', (data) => {
      // Log exactly what's inside a player_chat packet
      log('info', `[PLAYER_CHAT PACKET RECEIVED]: ${JSON.stringify(data)}`);
      
      try {
        let username = data.senderName; 
        
        // Try parsing the unsignedChatContent if present
        let plainMsg = data.plainMessage || '';
        if (!plainMsg && data.unsignedChatContent) {
            try {
                plainMsg = extractChatStrings(JSON.parse(data.unsignedChatContent)).join(' ');
            } catch(e) { plainMsg = data.unsignedChatContent; }
        }
        
        // Fallback: try extraction from components if plainMessage/unsignedContent fails
        if (!plainMsg && data.formattedMessage) {
             plainMsg = extractChatStrings(JSON.parse(data.formattedMessage)).join(' ');
        }
        
        log('info', `[PLAYER_CHAT PARSED]: user=${username} msg=${plainMsg}`);
        
        if (username && plainMsg && username !== bot.username) {
          emit({
            type: 'chat',
            player: username,
            uuid: data.sender || username,
            message: plainMsg,
            whisper: false,
          });
        }
      } catch (e) {
        log('error', `Error parsing player_chat packet: ${e.message}`);
      }
    });

    // 3. Handle system_chat (1.19+ system/server chat packet)
    bot._client.on('system_chat', (data) => {
      try {
        const raw = data.content;
        const strings = extractChatStrings(raw);
        const fullText = strings.join(' ');
        log('info', `[SYSTEM_CHAT FLATTENED]: ${fullText}`);

        // Filter out system messages (join/leave, etc.) - these have translate keys
        // and don't represent actual player chat
        const translationKey = raw.translate || '';
        if (translationKey && /multiplayer\.player\.(joined|left)|commands\./.test(translationKey)) {
          log('info', `[SYSTEM_CHAT SKIPPED]: system message (translate=${translationKey})`);
          return;
        }

        // Try to extract player name and message from the flattened strings
        if (strings.length >= 2) {
          for (let i = 0; i < strings.length - 1; i++) {
            const candidateUser = strings[i];
            const candidateMsg = strings[i+1];
            if (candidateUser && candidateUser.length >= 2 && candidateUser.length <= 16 && /^[a-zA-Z0-9_]+$/.test(candidateUser)) {
              if (candidateUser !== bot.username && candidateMsg && candidateMsg !== candidateUser) {
                log('info', `[CHAT RECOVERED FROM NBT]: user=${candidateUser} msg=${candidateMsg}`);
                const player = bot.players[candidateUser];
                emit({
                  type: 'chat',
                  player: candidateUser,
                  uuid: player ? player.uuid : candidateUser,
                  message: candidateMsg,
                  whisper: false,
                });
                return;
              }
            }
          }
        }

        // Fallback regex match
        const match = fullText.match(/^[<\[]([a-zA-Z0-9_]{2,16})[>\]]\s+(.+)$/) || 
                      fullText.match(/^([a-zA-Z0-9_]{2,16}):\s+(.+)$/);
        if (match && match[1] !== bot.username) {
          emit({
            type: 'chat',
            player: match[1],
            uuid: bot.players[match[1]]?.uuid || match[1],
            message: match[2],
            whisper: false,
          });
        }
      } catch (e) {
        log('error', `Error parsing system_chat: ${e.message}`);
      }
    });
  }

  // In modern versions (1.19+ and especially ViaVersion), chat events often fire as 'message' (system/chat packets)
  // or 'messagestr' instead of the legacy 'chat' event. Let's capture all of them!
  bot.on('messagestr', (msg, position, jsonMsg) => {
    log('info', `[RAW MESSAGE] (pos=${position}): ${msg}`);
    if (position === 'game_info') return; // ignore actionbar
    
    // Parse typical chat formats: "<Player> Message" or "Player: Message" or "[Player] Message"
    const match = msg.match(/^[<\[]([a-zA-Z0-9_]{2,16})[>\]]\s+(.+)$/) || 
                  msg.match(/^([a-zA-Z0-9_]{2,16}):\s+(.+)$/) ||
                  msg.match(/^([a-zA-Z0-9_]{2,16})\s+whispers to you:\s+(.+)$/i) ||
                  msg.match(/^([a-zA-Z0-9_]{2,16})\s+->\s+you:\s+(.+)$/i);

    if (match) {
      const username = match[1];
      const message = match[2];
      const isWhisper = /whisper|->/i.test(msg);
      if (username === bot.username) return;

      const player = bot.players[username];
      emit({
        type: 'chat',
        player: username,
        uuid: player ? player.uuid : username,
        message: message,
        whisper: isWhisper,
      });
    }
  });

  bot.on('chat', (username, message, rawMessage, jsonMsg, matches) => {
    log('info', `[CHAT EVENT] <${username}> ${message}`);
    if (username === bot.username) return;
    const player = bot.players[username];
    emit({
      type: 'chat',
      player: username,
      uuid: player ? player.uuid : null,
      message,
      whisper: false,
    });
  });

  bot.on('whisper', (username, message, rawMessage, jsonMsg) => {
    log('info', `[WHISPER EVENT] <${username}> ${message}`);
    if (username === bot.username) return;
    const player = bot.players[username];
    emit({
      type: 'chat',
      player: username,
      uuid: player ? player.uuid : null,
      message,
      whisper: true,
    });
  });

  bot.on('playerJoined', (player) => {
    onlinePlayers.set(player.uuid, { name: player.username, position: player.entity ? player.entity.position : null });
    if (player.username !== bot.username) {
        emit({ type: 'join', player: player.username, uuid: player.uuid });
    }
  });

  bot.on('playerLeft', (player) => {
    onlinePlayers.delete(player.uuid);
    if (player.username !== bot.username) {
        emit({ type: 'leave', player: player.username, uuid: player.uuid });
    }
  });

  bot.on('death', () => {
    emit({ type: 'death', position: bot.entity ? posKey(bot.entity.position) : null });
    setTimeout(() => {
      if (bot && bot.entity && bot.entity.isDead) {
        bot.respawn();
      }
    }, 2500);
  });

  bot.on('message', (jsonMsg) => {
    const text = jsonMsg.toString();
    // Death messages often come through as system chat
    if (/\bwas (?:slain|killed|shot|blown up|burned|drowned|fell|impaled|pummeled)\b/i.test(text) && text.includes(bot.username)) {
      emit({ type: 'death_message', text });
    }
    // Advancements
    const advMatch = text.match(/has made the advancement \[(.+?)\]/);
    if (advMatch) {
      emit({ type: 'advancement', player: text.split(' ')[0], advancement: advMatch[1] });
    }
  });

  bot.on('entitySwingArm', (entity) => {
    if (!entity || entity.type !== 'player') return;
    const rec = aggression.get(entity.uuid) || { weaponHits: 0, fistHits: 0 };
    rec.lastSwing = Date.now();
    aggression.set(entity.uuid, rec);
  });

  bot.on('health', () => {
    if (!bot || !bot.entity) return;
    // correlate recent swings with health loss
    const now = Date.now();
    for (const [uuid, rec] of aggression) {
      if (rec.lastSwing && now - rec.lastSwing < 1500) {
        if (heldItemIsWeapon()) {
          rec.weaponHits += 1;
        } else {
          rec.fistHits += 1;
        }
        rec.lastSwing = null;
        aggression.set(uuid, rec);
        const p = onlinePlayers.get(uuid);
        emit({ type: 'aggression', player: p ? p.name : uuid, weapon: heldItemIsWeapon(), record: rec });
      }
    }
  });

  bot.on('move', () => {
    // throttle status emits
  });

  // periodic status + player position updates
  setInterval(() => {
    if (!bot || !bot.entity) return;
    for (const player of Object.values(bot.players)) {
      if (player.entity) {
        const existing = onlinePlayers.get(player.uuid) || { name: player.username };
        existing.position = player.entity.position;
        onlinePlayers.set(player.uuid, existing);
      }
    }
    emitStatus();
  }, 5000);
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  log('info', 'scheduling reconnect in 10s');
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    bot = createBot();
    setupBotEvents();
  }, 10000);
}

async function main() {
  startMcpServer();

  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

  // First non-empty line is config JSON, then switch to command mode.
  let gotConfig = false;
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (!gotConfig) {
      try {
        config = JSON.parse(trimmed);
        gotConfig = true;
        log('info', 'received config from parent');
      } catch (e) {
        log('warn', 'first line was not valid JSON, using env config');
        config = {};
        gotConfig = true;
        // still process this line as a command below if it looked like one
        if (trimmed.startsWith('{')) continue;
      }
      bot = createBot();
      setupBotEvents();
      continue;
    }
    try {
      const cmd = JSON.parse(trimmed);
      log('info', `received command: ${trimmed}`);
      await handleChatCommand(cmd);
    } catch (e) {
      log('error', 'bad stdin command: ' + e.message + '\n' + e.stack);
    }
  }

  shuttingDown = true;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (mcpServer) mcpServer.close();
  if (bot) bot.end();
}

process.on('SIGINT', () => {
  shuttingDown = true;
  if (bot) bot.end();
  if (mcpServer) mcpServer.close();
  process.exit(0);
});

// If no config arrives within 10s, start anyway with env defaults.
setTimeout(() => {
  if (!bot) {
    log('info', 'no config received, starting with environment defaults');
    config = {};
    bot = createBot();
    setupBotEvents();
  }
}, 10000);

main().catch(e => {
  log('error', 'fatal: ' + e.message);
  process.exit(1);
});
