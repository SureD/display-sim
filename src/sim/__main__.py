"""Keep ``python -m sim`` working during the package-name transition."""

import warnings

from tv_sim.cli import main

if __name__ == "__main__":
    warnings.warn(
        "python -m sim is deprecated; use python -m tv_sim or tv-sim", FutureWarning, stacklevel=2
    )
    main()
