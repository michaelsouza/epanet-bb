/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file sparspaksolver.h
//! \brief Description of the SparspakSolver class.

#ifndef SPARSPAKSOLVER_H_
#define SPARSPAKSOLVER_H_

#include "matrixsolver.h"

//! \class SparspakSolver
//! \brief Solves Ax = b using the SPARSPAK routines.
//!
//! This class is derived from the MatrixSolver class and provides an
//! interface to the SPARSPAK routines, originally developed by George
//! and Liu, for re-ordering, factorizing, and solving via Cholesky
//! decomposition a sparse, symmetric, positive definite set of linear
//! equations Ax = b.

class SparspakSolver : public MatrixSolver {
public:
  // Constructor/Destructor

  SparspakSolver(std::ostream &logger);
  ~SparspakSolver();

  // Methods

  int init(int nrows, int nnz, int *xrow, int *xcol);
  void reset();

  double getDiag(int i);
  double getOffDiag(int i);
  double getRhs(int i);

  void setDiag(int i, double a);
  void setRhs(int i, double b);
  void addToDiag(int i, double a);
  void addToOffDiag(int j, double a);
  void addToRhs(int i, double b);
  int solve(int n, double x[]);

  //! Serialize to JSON for SparspakSolver
  nlohmann::json to_json() const override {
    return {
        {"lnz", lnz ? nlohmann::json(std::vector<double>(lnz, lnz + nnzl))
                    : nlohmann::json(nullptr)},
        {"diag", diag ? nlohmann::json(std::vector<double>(diag, diag + nrows))
                      : nlohmann::json(nullptr)},
        {"rhs", rhs ? nlohmann::json(std::vector<double>(rhs, rhs + nrows))
                    : nlohmann::json(nullptr)}};
  }

  //! Deserialize from JSON for SparspakSolver
  void from_json(const nlohmann::json &j) override {
    if (lnz) {
      std::vector<double> lnz_vec = j.at("lnz").get<std::vector<double>>();
      std::copy(lnz_vec.begin(), lnz_vec.end(), lnz);
    }

    if (diag) {
      std::vector<double> diag_vec = j.at("diag").get<std::vector<double>>();
      std::copy(diag_vec.begin(), diag_vec.end(), diag);
    }

    if (rhs) {
      std::vector<double> rhs_vec = j.at("rhs").get<std::vector<double>>();
      std::copy(rhs_vec.begin(), rhs_vec.end(), rhs);
    }
  }

  void copy_to(MatrixSolverData &data) const override {
    // resize if necessary
    if (data.lnz.size() < nnzl) {
      data.lnz.resize(nnzl);
    }
    if (data.diag.size() < nrows) {
      data.diag.resize(nrows);
    }
    if (data.rhs.size() < nrows) {
      data.rhs.resize(nrows);
    }
    // copy values
    std::copy(lnz, lnz + nnzl, data.lnz.begin());
    std::copy(diag, diag + nrows, data.diag.begin());
    std::copy(rhs, rhs + nrows, data.rhs.begin());
  }

  void copy_from(const MatrixSolverData &data) override {
    std::copy(data.lnz.begin(), data.lnz.end(), lnz);
    std::copy(data.diag.begin(), data.diag.end(), diag);
    std::copy(data.rhs.begin(), data.rhs.end(), rhs);
  }

private:
  int nrows;    // number of rows in system Ax = b
  int nnz;      // number of non-zero off-diag. coeffs. in A
  int nnzl;     // number of non-zero off-diag. coeffs. in factorized matrix L
  int *perm;    // permutation of rows in A
  int *invp;    // inverse row permutation
  int *xlnz;    // index vector for non-zero entries in L
  int *xnzsub;  // index vector for entries of nzsub
  int *nzsub;   // column indexes for non-zero entries in each row of L
  int *xaij;    // maps off-diag. coeffs. of A to lnz
  int *link;    // work array
  int *first;   // work array
  double *lnz;  // off-diag. coeffs. of factorized matrix L
  double *diag; // diagonal coeffs. of A
  double *rhs;  // right hand side vector
  double *temp; // work array
  std::ostream &msgLog;
};

#endif
