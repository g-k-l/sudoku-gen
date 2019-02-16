import sys
import numpy as np
from .gen_sol import (main, backtrack_iter, create_puzzle_from_board,
    starting_board)
from .client import client

if __name__ == "__main__":
    if sys.argv[1] == "play":
        sys.exit(client() or 0)     
    elif sys.argv[1] == "solve":
        board = np.array([int(c) for c in sys.argv[2]]).reshape(9, 9)
        solution = backtrack_iter(board)
        print(solution)
        sys.exit(0)
    elif sys.argv[1] == "gen":
        board = starting_board()
        puzzle = create_puzzle_from_board(backtrack_iter(board))
        print(puzzle)
        sys.exit(0)
    else:
        try:
            n_jobs = int(sys.argv[1])
        except (IndexError, ValueError):
            n_jobs = None 
        sys.exit(main(n_jobs) or 0)
