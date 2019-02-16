"""
This file contains a backtracking
sudoku solver for generating fully
-populated puzzles.
"""
from collections import defaultdict
from functools import lru_cache
import math
import multiprocessing as mp
import queue
import sys

import numpy as np

from .db import insert_solutions, insert_puzzles, get_conn
from .constants import BOARD_DIM, COMPLETE_ROW, DEBUG, BLOCK_ARRAY


def is_filled(board):
    if np.count_nonzero(board) == BOARD_DIM**2:
        return True
    return False


@lru_cache()
def squares():
    """
    Generates "groups" which is a dictionary
    grouping sudoku puzzle indices belonging
    to the same square. Also generates the
    reverse lookup "lookup" from index to group.
    """
    groups = defaultdict(set)
    lookup = defaultdict(int)
    for x_arr, y_arr in zip(*np.indices((9, 9))):
        for x, y in zip(x_arr, y_arr):
            groups[BLOCK_ARRAY[x, y]].add((x, y))
            lookup[(x, y)] = BLOCK_ARRAY[x, y]
    return groups, lookup


def choices_from_square(board, x, y):
    groups, lookup = squares()
    g = lookup[(x, y)]
    cells_in_g = groups[g]
    numbers_in_g = {board[a, b] for a, b in cells_in_g}
    return COMPLETE_ROW - numbers_in_g


def construct_candidates(board, x, y):
    """
    Get eligible candidates for the cell at (x, y)
    """
    possible_from_row = COMPLETE_ROW - set(board[x, :])
    possible_from_col = COMPLETE_ROW - set(board[:, y])
    possible_from_square = choices_from_square(board, x, y)
    if DEBUG:
        print("================")
        print(board)
        print("x: ", x)
        print("y: ", y)
        print("from rows:", possible_from_row)
        print("from cols:", possible_from_col)
        print("from block:", possible_from_square)
        print(possible_from_col & possible_from_row & possible_from_square)
    return possible_from_col & possible_from_row & possible_from_square


def get_unfilled_cell_rand(board):
    zero_indices = np.argwhere(board == 0)
    if len(zero_indices) > 0:
        cell_index = np.random.randint(len(zero_indices))
    else:
        raise IndexError("No unfilled cell remaining!")
    x, y = zero_indices[cell_index]
    return x, y


def propagate_constraint(board):
    """Fill out squares for which there is only
        one choice remaining after applying the
        previous guess"""
    x_matrix, y_matrix = np.indices((9, 9))
    for x_arr, y_arr in zip(x_matrix, y_matrix):
        for x, y in zip(x_arr, y_arr):
            candidates = construct_candidates(board, x, y)
            if len(candidates) == 1:
                board[x, y] = candidates.pop()
    return board


def backtrack_iter(board):
    stack = [board]
    while True:
        board = stack.pop()
        if is_filled(board):
            return board
        x, y = get_unfilled_cell_rand(board)
        sys.stdout.write("# filled: {}\r".format(np.count_nonzero(board)))
        sys.stdout.flush()

        candidates = construct_candidates(board, x, y)
        for candidate in candidates:
            copied = board.copy()
            copied[x, y] = candidate
            copied = propagate_constraint(copied)
            stack.append(copied)


def board_in_solutions(board, solutions):
    for sol in solutions:
        if np.all(np.equal(board, sol)):
            return True
    return False


def solution_unique(board):
    """Like backtrack_iter, but its main purpose is to
        check for uniqueness of generated puzzles from
        solutions"""
    stack, solutions = [board], []
    while True:
        try:
            board = stack.pop()
        except IndexError:
            if len(solutions) == 1:
                return True
            return False
        if is_filled(board):
            if not board_in_solutions(board, solutions):
                solutions.append(board)
            if len(solutions) > 1:
                return False
            continue
        x, y = get_unfilled_cell_rand(board)
        sys.stdout.write("# filled: {}\r".format(np.count_nonzero(board)))
        sys.stdout.flush()

        candidates = construct_candidates(board, x, y)
        for candidate in candidates:
            copied = board.copy()
            copied[x, y] = candidate
            copied = propagate_constraint(copied)
            stack.append(copied)


def prefill_diagonals(board):
    """
    Fill the diagonal squares (groups 0, 4, 8)
    first prior to backtracking to reduce the
    problem space.
    """
    groups, __ = squares()
    for n in (0, 4, 8):
        arr = np.arange(1, 10)
        np.random.shuffle(arr)
        for (x, y), k in zip(groups[n], arr):
            board[x, y] = k
    return board


def _create_puzzle(board):
    positions = np.arange(81)
    np.random.shuffle(positions)
    positions = list(positions)

    while True:
        if not positions:
            return board

        position = positions.pop()
        x = position % BOARD_DIM
        y = math.floor(position / BOARD_DIM)

        old_val = board[x, y]
        board[x, y] = 0
        if not solution_unique(board):
            board[x, y] = old_val


def starting_board():
    return prefill_diagonals(
        np.zeros((BOARD_DIM, BOARD_DIM,), dtype=int))


def create_solution(input_q, output_q):
    while True:
        board = input_q.get()
        try:
            board, ct = board
            output_q.put((backtrack_iter(board), ct))
            print("\nCreated Solution {}".format(ct))
            input_q.task_done()
        except queue.Full:
            sys.stdout.write("$$ sol_q is full!\r")
            sys.stdout.flush()


def create_puzzle(input_q, output_q):
    while True:
        sol = input_q.get()
        sol, ct = sol
        puzzle = sol.copy()
        try:
            output_q.put((_create_puzzle(puzzle), sol, ct,))
            print("\nCreated Puzzle {}".format(ct))
            input_q.task_done()
        except queue.Full:
            sys.stdout.write("## puzzle_q is full!\r")
            sys.stdout.flush()


def to_db(input_q, db_batch_size):
    conn = get_conn()
    conn.autocommit = True
    cursor = conn.cursor()
    results = []
    sentinel = True
    while True:
        if not input_q.empty():
            board_and_sol = input_q.get()
            results.append(board_and_sol)

        if not results and sentinel is None:
            break
        if len(results) >= db_batch_size or sentinel is None:
            puzzles, boards, cts = zip(*results)
            insert_solutions(boards, cursor)
            insert_puzzles(zip(puzzles, boards), cursor)
            print("Stored {} puzzles and {} sols to db".format(
                len(results), len(boards)))
            [input_q.task_done() for __ in range(len(results))]
            results = []


def main(n_jobs, queue_size=100):
    if n_jobs:
        db_batch_size = min(math.floor(queue_size/2), n_jobs)
    else:
        db_batch_size = math.floor(queue_size/2)
    sol_q = mp.JoinableQueue(maxsize=queue_size)
    puzzle_q = mp.JoinableQueue(maxsize=queue_size)
    db_q = mp.JoinableQueue(maxsize=db_batch_size)

    create_ps, puzzle_ps = [], []
    for __ in range(3):
        create_p = mp.Process(target=create_solution, args=(sol_q, puzzle_q,))
        create_p.daemon = True
        create_p.start()

    for __ in range(5):
        create_ps.append(create_p)
        puzzle_p = mp.Process(target=create_puzzle, args=(puzzle_q, db_q,))
        puzzle_p.daemon = True
        puzzle_p.start()

    puzzle_ps.append(puzzle_p)
    db_p = mp.Process(target=to_db, args=(db_q, db_batch_size,))
    db_p.daemon = True
    db_p.start()

    enqueued = 0
    while True:
        if n_jobs is not None and enqueued >= n_jobs:
            break

        if not sol_q.full():
            sol_q.put((starting_board(), enqueued,))
            enqueued += 1
            print("== {} job(s) enqueued".format(enqueued))
        else:
            sys.stdout.write("== sol_q is full!\r")
            sys.stdout.flush()
    sol_q.join()
    print("Solution process shutdown.")
    puzzle_q.join()
    print("Puzzle process shutdown.")
    db_q.join()
    print("Finished.")
