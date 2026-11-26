// SPDX-License-Identifier: AGPL-3.0-only
// Optional transport adapter only. Simulation and schema classes remain in the pinned engine JAR.
package battlecode.server;
import battlecode.schema.*;
import java.nio.ByteBuffer;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;

public final class NetServer {
    // Upstream emits FlatBuffer structs in its action union although the generated accessor accepts Table.
    // Override only the union cursor reset, then use the unchanged generated struct decoders.
    private static final class StructCursor extends com.google.flatbuffers.Table {
        @Override protected void __reset(int position, ByteBuffer buffer) { bb_pos = position; bb = buffer; }
        SpawnAction spawn() { return new SpawnAction().__assign(bb_pos, bb); }
        DieAction die() { return new DieAction().__assign(bb_pos, bb); }
        PlaceDirt place() { return new PlaceDirt().__assign(bb_pos, bb); }
        BreakDirt remove() { return new BreakDirt().__assign(bb_pos, bb); }
        CheesePickup pickup() { return new CheesePickup().__assign(bb_pos, bb); }
        CheeseSpawn cheeseSpawn() { return new CheeseSpawn().__assign(bb_pos, bb); }
    }
    private final Path destination;
    private final Map<Integer, int[]> robots = new TreeMap<>();
    private int width, height, round;
    private boolean[] walls = new boolean[0], dirt = new boolean[0], cheese = new boolean[0];
    private final int[][] teams = new int[2][4];
    private boolean finished, disabled;
    private long lastWrite;
    public NetServer(int port, boolean waitForClient) {
        String path = System.getProperty("bio.live.path");
        destination = path == null ? null : Path.of(path);
    }
    public void start() { }
    private void spawn(SpawnAction s) {
        robots.put(s.id(), new int[]{s.x(), s.y(), s.team(), s.robotType(), 0, 0, s.dir()});
    }
    public synchronized void addEvent(byte[] event) {
        if (destination == null || disabled) return;
        try {
            EventWrapper wrapper = EventWrapper.getRootAsEventWrapper(ByteBuffer.wrap(event));
            if (wrapper.eType() == Event.MatchHeader) {
                MatchHeader header = (MatchHeader) wrapper.e(new MatchHeader());
                GameMap map = header.map();
                width = map.size().x(); height = map.size().y();
                if (width < 1 || height < 1 || width > 256 || height > 256) { disabled = true; return; }
                walls = new boolean[width * height]; dirt = new boolean[width * height]; cheese = new boolean[width * height];
                for (int i = 0; i < walls.length; i++) {
                    walls[i] = i < map.wallsLength() && map.walls(i);
                    dirt[i] = i < map.dirtLength() && map.dirt(i);
                    cheese[i] = i < map.cheeseLength() && map.cheese(i) > 0;
                }
                robots.clear(); round = 0; finished = false;
                InitialBodyTable bodies = map.initialBodies();
                for (int i = 0; i < bodies.spawnActionsLength(); i++) spawn(bodies.spawnActions(i));
                write(true);
            } else if (wrapper.eType() == Event.Round) {
                Round update = (Round) wrapper.e(new Round());
                round = update.roundId();
                for (int i = 0; i < update.teamIdsLength(); i++) {
                    int team = update.teamIds(i) - 1;
                    if (team >= 0 && team < 2) {
                        teams[team][0] = update.teamCheeseTransferred(i); teams[team][1] = update.teamCatDamage(i);
                        teams[team][2] = update.teamAliveRatKings(i); teams[team][3] = update.teamAliveBabyRats(i);
                    }
                }
                for (int i = 0; i < update.turnsLength(); i++) {
                    Turn turn = update.turns(i);
                    for (int j = 0; j < turn.actionsLength(); j++) {
                        byte type = turn.actionsType(j);
                        if (type == Action.SpawnAction) spawn(((StructCursor) turn.actions(new StructCursor(), j)).spawn());
                        else if (type == Action.DieAction) robots.remove(((StructCursor) turn.actions(new StructCursor(), j)).die().id());
                        else if (type == Action.UpgradeToRatKing && robots.containsKey(turn.robotId())) robots.get(turn.robotId())[3] = 2;
                        else if (type == Action.PlaceDirt) {
                            int loc = ((StructCursor) turn.actions(new StructCursor(), j)).place().loc();
                            if (loc >= 0 && loc < dirt.length) dirt[loc] = true;
                        } else if (type == Action.BreakDirt) {
                            int loc = ((StructCursor) turn.actions(new StructCursor(), j)).remove().loc();
                            if (loc >= 0 && loc < dirt.length) dirt[loc] = false;
                        }
                        else if (type == Action.CheesePickup) {
                            int loc = ((StructCursor) turn.actions(new StructCursor(), j)).pickup().loc();
                            if (loc >= 0 && loc < cheese.length) cheese[loc] = false;
                        } else if (type == Action.CheeseSpawn) {
                            CheeseSpawn action = ((StructCursor) turn.actions(new StructCursor(), j)).cheeseSpawn();
                            if (action.loc() >= 0 && action.loc() < cheese.length) cheese[action.loc()] = action.amount() > 0;
                        }
                        // All indicators, labels, profiler data and arbitrary strings are deliberately omitted.
                    }
                    int[] bot = robots.get(turn.robotId());
                    if (bot != null) { bot[0] = turn.x(); bot[1] = turn.y(); bot[4] = turn.health(); bot[5] = turn.cheese(); bot[6] = turn.dir(); }
                }
                for (int i = 0; i < update.diedIdsLength(); i++) robots.remove(update.diedIds(i));
                write(false);
            } else if (wrapper.eType() == Event.MatchFooter || wrapper.eType() == Event.GameFooter) {
                finished = true; write(true);
            }
        } catch (Exception error) { disabled = true; } // viewer failure must never decide or interrupt a game
    }
    private void cells(StringBuilder out, String key, boolean[] cells) {
        out.append(",\"").append(key).append("\":[");
        boolean comma = false;
        for (int i = 0; i < cells.length; i++) if (cells[i]) {
            if (comma) out.append(','); comma = true;
            out.append("{\"x\":").append(i % width).append(",\"y\":").append(i / width).append('}');
        }
        out.append(']');
    }
    private void write(boolean force) throws Exception {
        if (width == 0) return;
        long now = System.currentTimeMillis();
        if (!force && now - lastWrite < 100) return; // latest state, at most 10 writes/second
        lastWrite = now;
        StringBuilder out = new StringBuilder();
        out.append("{\"width\":").append(width).append(",\"height\":").append(height)
            .append(",\"round\":").append(round).append(",\"updated_at\":").append(now / 1000.0)
            .append(",\"finished\":").append(finished).append(",\"robots\":[");
        boolean comma = false;
        for (Map.Entry<Integer,int[]> entry : robots.entrySet()) {
            if (comma) out.append(','); comma = true;
            int[] b = entry.getValue();
            out.append("{\"id\":").append(entry.getKey()).append(",\"x\":").append(b[0]).append(",\"y\":").append(b[1])
                .append(",\"team\":").append(b[2]).append(",\"kind\":").append(b[3]).append(",\"health\":").append(b[4])
                .append(",\"cheese\":").append(b[5]).append(",\"dir\":").append(b[6]).append('}');
        }
        out.append(']'); cells(out, "walls", walls); cells(out, "dirt", dirt); cells(out, "cheese", cheese);
        out.append(",\"teams\":[");
        for (int i = 0; i < 2; i++) {
            if (i > 0) out.append(',');
            out.append("{\"team\":").append(i+1).append(",\"cheese_transferred\":").append(teams[i][0])
                .append(",\"cat_damage\":").append(teams[i][1]).append(",\"alive_kings\":").append(teams[i][2])
                .append(",\"alive_rats\":").append(teams[i][3]).append('}');
        }
        out.append("]}");
        Path temp = Files.createTempFile(destination.getParent(), ".live-", ".tmp", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        try {
            Files.writeString(temp, out.toString());
            Files.move(temp, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temp); }
    }
    public synchronized void finish() {
        if (disabled || destination == null) return;
        try { finished = true; write(true); } catch (Exception error) { disabled = true; }
    }
}
