pkgs <- c("fuzzyjoin", "tictoc")
for(p in pkgs) {
  if(!requireNamespace(p, quietly=TRUE)) {
    install.packages(p, repos="https://cran.r-project.org")
  }
}
cat("All packages OK\n")
