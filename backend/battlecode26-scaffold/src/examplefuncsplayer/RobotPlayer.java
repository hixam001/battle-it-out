
package examplefuncsplayer;

import battlecode.common.*;

import java.util.Random;

public class RobotPlayer {

    static int turnCount = 0;
    static final Random rng = new Random(6147);

    static final Direction[] directions = {
        Direction.NORTH,
        Direction.NORTHEAST,
        Direction.EAST,
        Direction.SOUTHEAST,
        Direction.SOUTH,
        Direction.SOUTHWEST,
        Direction.WEST,
        Direction.NORTHWEST
    };

    static Direction preferredDirection = Direction.NORTH;
    static int blockedTurns = 0;

    public static void run(RobotController rc) throws GameActionException {
        System.out.println("Battle It Out bot started!");

        while (true) {
            turnCount++;

            try {
                Direction current = rc.getDirection();

                // Keep moving forward when the path is clear.
                if (rc.canMoveForward()) {
                    rc.moveForward();
                    blockedTurns = 0;
                } else {
                    blockedTurns++;

                    // Try a different direction rather than turning randomly
                    // every time the robot encounters an obstacle.
                    Direction next = chooseDirection(rc, current);

                    if (next != null && rc.canTurn(next)) {
                        rc.turn(next);
                        preferredDirection = next;
                    }
                }

                rc.setIndicatorString(
                    "Turn: " + turnCount
                    + " | Direction: " + rc.getDirection()
                    + " | Blocked: " + blockedTurns
                );

            } catch (GameActionException e) {
                System.out.println("Action failed on turn " + turnCount);
            } catch (Exception e) {
                System.out.println("Bot error on turn " + turnCount);
                e.printStackTrace();
            } finally {
                Clock.yield();
            }
        }
    }

    static Direction chooseDirection(
        RobotController rc,
        Direction current
    ) throws GameActionException {

        // Prefer directions close to the current heading.
        // Shuffle the order slightly so the bot does not get stuck
        // repeating the same route indefinitely.
        Direction[] candidates = new Direction[8];
        int start = rng.nextInt(8);

        for (int i = 0; i < 8; i++) {
            candidates[i] = directions[(start + i) % 8];
        }

        // Prefer continuing in the same direction when possible.
        if (blockedTurns < 2) {
            for (Direction direction : candidates) {
                if (direction == current && rc.canTurn(direction)) {
                    return direction;
                }
            }
        }

        // Otherwise choose a legal alternative.
        for (Direction direction : candidates) {
            if (direction != current && rc.canTurn(direction)) {
                return direction;
            }
        }

        return null;
    }
}
